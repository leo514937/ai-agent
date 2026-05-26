package main

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/kafka"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
	"golang.org/x/net/html"
)

const pDateFormat = "2006-01-02"
const sqlFormat = `
select
  p_date,
  cast(member_id as bigint) as member_id,
  scene,
  cast(0 as bigint) as publish_time,
  query_merge,
  url
from
  (
    select
      p_date,
      member_id,
      scene,
      get_json_object(process_tracing, '$.query_merge') as query_merge,
      url,
      cast(0 as bigint) as publish_time
    from
      logs.aisp_common_tracing LATERAL VIEW explode(
        split(
          regexp_replace(
            regexp_replace(
              regexp_replace(
                get_json_object(process_tracing, '$.original_recall_item[].url'),
                '"",',
                ''
              ),
              '","',
              ','
            ),
            '\\["|"\\]',
            ''
          ),
          ','
        )
      ) exploded_t AS url
      
    where
      p_date = '%s'
  ) t
where
  t.url not like '%%zhihu.com%%'
group by   
  p_date,
  member_id,
  scene,
  query_merge,
  url,
  publish_time
`

func main() {
	ctx := context.Background()

	hiveClient := resource.NewHiveClient()
	defer hiveClient.Close()

	beginDate, _ := time.Parse(pDateFormat, "2024-07-23")
	endDate, _ := time.Parse(pDateFormat, "2024-07-28")

	for d := beginDate; d.Before(endDate); d = d.AddDate(0, 0, 1) {
		log.Infof(ctx, "start to crawl data for date: %s", d.Format(pDateFormat))
		importData(ctx, hiveClient, d)
	}
}

func processByLogics(ctx context.Context, webPages []*model.CrawledWebPage) []*model.CrawledWebPage {
	logics := []Logic{
		NewFillFieldsByHistoryLogic(30),
		NewCrawlWebPageTextLogic(50),
		NewFilterIfEmptyLogic("content"),
	}

	for _, plugin := range logics {
		webPages, _ = plugin.Process(ctx, webPages)
	}

	return webPages
}

type Logic interface {
	Process(ctx context.Context, webPages []*model.CrawledWebPage) ([]*model.CrawledWebPage, error)
}

func NewFillFieldsByHistoryLogic(expireTimeDays int) *FillFieldsByHistoryLogic {
	return &FillFieldsByHistoryLogic{
		expireTimeDays:  expireTimeDays,
		fieldNames:      []string{"title", "raw_content"},
		expireTimeField: "crawl_at",
	}
}

type FillFieldsByHistoryLogic struct {
	expireTimeDays  int
	fieldNames      []string
	expireTimeField string
}

// Process 填充历史数据，[now-expireTimeDays, now) 之间的数据
func (c *FillFieldsByHistoryLogic) Process(ctx context.Context, webPages []*model.CrawledWebPage) ([]*model.CrawledWebPage, error) {
	var limit int64 = 100

	nowDate := time.Now()
	beginDate := nowDate.AddDate(0, 0, -c.expireTimeDays)
	endDate := nowDate.AddDate(0, 0, -1)

	urlHashs := lo.Map(webPages, func(webPage *model.CrawledWebPage, _ int) int64 {
		return webPage.UrlHash
	})
	crawledWebPages, err := impl.DefaultCrawledWebDao.BatchGetCrawled(ctx, urlHashs, beginDate, endDate, int(limit))
	if err != nil {
		log.Errorf(ctx, "BatchGetCrawled failed. err=%+v", err)
		return crawledWebPages, err
	}

	crawledUrlMaps := map[int64]*model.CrawledWebPage{}
	for _, crawledWebPage := range crawledWebPages {
		crawledUrlMaps[crawledWebPage.UrlHash] = crawledWebPage
	}

	for _, webPage := range webPages {
		if _, ok := crawledUrlMaps[webPage.UrlHash]; ok {
			webPage.Title = crawledUrlMaps[webPage.UrlHash].Title
			webPage.RawContent = crawledUrlMaps[webPage.UrlHash].RawContent
		}
	}

	return webPages, nil
}

func NewCrawlWebPageTextLogic(parallelism int) *CrawlWebPageTextLogic {
	return &CrawlWebPageTextLogic{
		parallelism: parallelism,
	}
}

type CrawlWebPageTextLogic struct {
	parallelism int
}

func (c *CrawlWebPageTextLogic) Process(ctx context.Context, webPages []*model.CrawledWebPage) ([]*model.CrawledWebPage, error) {
	totalCount := len(webPages)

	var limit = 100

	beginIndex := 0
	leftCount := totalCount
	for leftCount > 0 {
		endIndex := beginIndex + limit
		if endIndex > totalCount {
			endIndex = totalCount
		}
		batchWebPages := webPages[beginIndex:endIndex]

		startTime := time.Now()

		windowSize := len(batchWebPages) / c.parallelism
		if len(batchWebPages)%c.parallelism != 0 {
			windowSize++
		}
		safe_group.WindowGroupDo(windowSize, batchWebPages, func(ids interface{}) {
			windowBatchWebPages := ids.([]*model.CrawledWebPage)
			for _, webPage := range windowBatchWebPages {
				if webPage.Title != "" && webPage.RawContent != "" {
					continue
				}

				log.Infof(ctx, "begin crawl url: %s", webPage.Url)
				pageContent, err := rpcImpl.DefaultCrawlerRpc.RealTimeCrawler(ctx, webPage.Url)

				if err != nil {
					log.Errorf(ctx, "RealTimeCrawler failed. url=%s. err=%+v", webPage.Url, err)
					return
				}

				if !isValid(pageContent.Title) || !isValid(pageContent.Content) {
					log.Warnf(ctx, "RealTimeCrawler content invalid. url=%s.", webPage.Url)
					continue
				}
				webPage.RawContent = pageContent.Content
				webPage.Title = pageContent.Title
				webPage.Content = parseHtml(pageContent.Content)
				now := time.Now()
				webPage.CrawlAt = &now
			}

			return
		})

		log.Infof(ctx, "batch crawl done. beginIndex: %d, endIndex: %d, cost: %v", beginIndex, endIndex, time.Since(startTime))

		leftCount -= limit
	}

	return webPages, nil
}

func NewFilterIfEmptyLogic(field string) *FilterIfEmptyLogic {
	return &FilterIfEmptyLogic{
		field: field,
	}
}

type FilterIfEmptyLogic struct {
	field string
}

func (c *FilterIfEmptyLogic) Process(ctx context.Context, webPages []*model.CrawledWebPage) ([]*model.CrawledWebPage, error) {

	webPages = lo.Filter(webPages, func(webPage *model.CrawledWebPage, _ int) bool {
		return webPage.Content != ""
	})

	return webPages, nil
}

func importData(ctx context.Context, hiveClient *resource.HiveClient, d time.Time) {
	sql := fmt.Sprintf(sqlFormat, d.Format(pDateFormat))
	cursor := hiveClient.GetCursor()
	cursor.Exec(ctx, "set hive.strict.checks.large.query=false")
	cursor.Exec(ctx, "set hive.mapred.mode=nonstrict")
	cursor.Exec(ctx, sql)

	if cursor.Err != nil {
		log.Errorf(ctx, "hive Err:%v", cursor.Err)
		return
	}
	log.Infof(ctx, "start sync job")
	syncCount := 0
	crawledWebPages := make([]*model.CrawledWebPage, 0)
	urls := map[string]int{}
	for cursor.HasMore(ctx) {

		crawledWeb := model.CrawledWebPage{}
		cursor.FetchOne(ctx, &crawledWeb.PDate, &crawledWeb.MemberId, &crawledWeb.Scene, &crawledWeb.PublishTime, &crawledWeb.QueryMerge, &crawledWeb.Url)
		if ctx.Err() != nil {
			log.Errorf(ctx, "fetch one error. err:%v", ctx.Err())
			return
		}

		crawledWeb.UrlHash = util.HashToInt64(crawledWeb.Url)
		crawledWebPages = append(crawledWebPages, &crawledWeb)

		domain := getDomain(crawledWeb.Url)
		urls[domain] += 1

		syncCount++
		if syncCount%100 == 0 {
			log.Infof(ctx, "begin sync data count:%d", syncCount)

			beforeCount := len(crawledWebPages)
			crawledWebPages = processByLogics(ctx, crawledWebPages)
			afterCount := len(crawledWebPages)
			log.Infof(ctx, "crawl url done. date:%v, count: %d, beforeCount: %d, afterCount: %d", d, syncCount, beforeCount, afterCount)

			if len(crawledWebPages) != 0 {
				_, err := impl.DefaultCrawledWebDao.BatchInsert(ctx, crawledWebPages)
				if err != nil {
					log.Errorf(ctx, "batch insert error. err:%v", err)
				}
			}

			for _, page := range crawledWebPages {
				sendToMq(ctx, page)
			}
			log.Infof(ctx, "sync data done. date:%v, count:%d", d, syncCount)

			crawledWebPages = make([]*model.CrawledWebPage, 0)
		}
	}

	printTop100(urls)
}

// urls按照value排序输出前100
func printTop100(urls map[string]int) {
	pairs := lo.ToPairs(urls)
	sort.Slice(pairs, func(i, j int) bool {
		return pairs[i].Value > pairs[j].Value
	})

	for i, pair := range pairs[:100] {
		fmt.Printf("top_url: %d. %s: %d\n", i+1, pair.Key, pair.Value)
	}
}

func getDomain(url string) string {
	if !strings.Contains(url, "://") {
		return ""
	}

	path := strings.Split(url, "//")[1]
	if !strings.Contains(path, "/") {
		return ""
	}
	return strings.Split(path, "/")[0]
}

var htmlSpaceRe *regexp.Regexp

var spaceRe *regexp.Regexp

func init() {
	htmlSpaceRe = regexp.MustCompile(`&nbsp;`)

	spaceRe = regexp.MustCompile(`[\xa0\x1f]`)
}

func parseHtml(rawHtml string) string {

	doc, err := html.Parse(strings.NewReader(rawHtml))
	if err != nil {
		fmt.Println("Error:", err)
		return ""
	}

	text := parseTextNode(doc)
	text = htmlSpaceRe.ReplaceAllString(text, " ")
	text = spaceRe.ReplaceAllString(text, " ")
	return strings.TrimSpace(text)
}

func parseTextNode(body *html.Node) string {
	var result string
	for c := body.FirstChild; c != nil; c = c.NextSibling {
		if c.Type == html.ElementNode && (c.Data == "head" || c.Data == "script" || c.Data == "style" || c.Data == "br") {
			continue
		}
		if c.Type == html.ElementNode {
			result += parseTextNode(c)
		} else if c.Type == html.TextNode {
			if c.Data == "\n" {
				continue
			}
			result += c.Data
		}
	}
	return result
}

func sendToMq(ctx context.Context, webPage *model.CrawledWebPage) {
	producer, err := kafka.GetProducer(context.Background(), string(macro.CrawledWebPage))
	if err != nil {
		log.WithError(ctx, err).Error(ctx, "get producer failed:%s", macro.CrawledWebPage)
		return
	}

	producer.AsyncSend(ctx, &kafka.ProducerMessage{
		Value: []byte(util.GetJSONIgnoreError(webPage)),
	})
	log.Infof(ctx, "send to mq success. url:%s. title:%s. content:%s", webPage.Url, webPage.Title, webPage.RawContent)
}

// 判断文本中是否有很多非中英文、标点，如果是的话，认为被反爬拦截不可用
func isValid(str string) bool {
	if strings.Contains(str, "百度安全验证") {
		return false
	}

	validCount := 0
	for _, c := range str {
		if unicode.Is(unicode.Han, c) || unicode.IsLetter(c) || unicode.IsDigit(c) || unicode.IsSpace(c) || unicode.IsPunct(c) || unicode.IsSymbol(c) {
			validCount++
		}
	}

	allLength := utf8.RuneCountInString(str)
	return float32(validCount)/float32(allLength) > 0.8
}
