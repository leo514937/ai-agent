package impl

import (
	"context"
	"fmt"
	"net/http"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/spf13/cast"
)

// https://aq6ky2b8nql.feishu.cn/wiki/RXEOw02rFiwzGSkd9mUcqoeAnNK
// 只兼容了文本搜索的字段 video 和 image 类本期用不到
type BoChaClientImpl struct {
	httpClient *util.HttpClient
}

var DefaultBoChaClient rpc.BoChaClientHTTP

const (
	boChaEndpoint string = "https://api.bochaai.com/v1/web-search"
)

func init() {
	DefaultBoChaClient = NewBoChaClientHttp()
}

func NewBoChaClientHttp() rpc.BoChaClientHTTP {
	return &BoChaClientImpl{
		httpClient: util.NewHttpClient(http.MethodPost, boChaEndpoint, 3000*time.Millisecond),
	}
}

type boChaAnswerRaw struct {
	Code  int    `json:"code"`
	Msg   string `json:"msg"`
	LogId string `json:"log_id"`
	Data  struct {
		Type         string `json:"_type"`
		QueryContext struct {
			OriginalQuery string `json:"originalQuery"`
		} `json:"queryContext"`
		WebPages struct {
			WebSearchURL          string `json:"webSearchUrl"`
			TotalEstimatedMatches int    `json:"totalEstimatedMatches"` // 搜索匹配的网页总数
			SomeResultsRemoved    bool   `json:"someResultsRemoved"`    // 结果中是否有被安全过滤
			Value                 []struct {
				ID         string `json:"id"`
				Name       string `json:"name"` // 网页的标题
				URL        string `json:"url"`
				DisplayURL string `json:"displayUrl"` // 显示的 URL（url decode后的格式）
				Snippet    string `json:"snippet"`    // 网页内容的简短描述
				Summary    string `json:"summary"`    // 网页内容的文本摘要，当请求参数中 summary 为 true 时显示此属性
				SiteName   string `json:"siteName"`   // 网页的网站名称
				SiteIcon   string `json:"siteIcon"`   // 网页的网站图标
				// 接口中返回的值（例如：2025-02-23T08:18:30Z）实际上要表达的是 UTC+8 北京时间2025-02-23 08:18:30，并非UTC时间。这个问题我们会在将来v2版本中修复。
				DateLastCrawled  time.Time `json:"dateLastCrawled"`  // 最后爬取时间
				CachedPageUrl    string    `json:"cachedPageUrl"`    // 网页的缓存页面URL
				Language         string    `json:"language"`         // 网页的语言
				IsFamilyFriendly bool      `json:"isFamilyFriendly"` // 是否为家庭友好的页面
				IsNavigational   bool      `json:"isNavigational"`   // 是否为导航性页面
			} `json:"value"`
		} `json:"webPages"`
	} `json:"data"`
}

func (c *BoChaClientImpl) Search(ctx context.Context, query string, topK int32, freshness rpc.BoChaFreshness, isSummary bool) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	logger := log.WithField(ctx, "BoChaSearch", query)

	begin := time.Now()
	body := map[string]string{
		"query":     query,
		"freshness": string(freshness),
		"summary":   cast.ToString(isSummary),
		"count":     cast.ToString(topK),
	}

	searchResp := &boChaAnswerRaw{}
	var err error
	runFunc := func(ctx context.Context) error {
		errTmp := c.httpClient.Do(ctx, map[string]string{
			"Authorization": fmt.Sprintf("Bearer %s", config.GetString(macro.BoChaTokenConfigName, "")),
			"Content-Type":  "application/json",
		}, nil, body, searchResp)
		if err != nil {
			err = errTmp
			return err
		}
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	elapsedTime := time.Since(begin).Milliseconds()
	if elapsedTime > 1500 {
		logger.Infof(ctx, "LogId:[%s] elapsedTime: %d", searchResp.LogId, elapsedTime)
	}
	if err != nil {
		logger.Warnf(ctx, "LogId:[%s] failed: %v", searchResp.LogId, err)
		return nil, err
	}
	if searchResp.Code != http.StatusOK {
		logger.Warnf(ctx, "LogId:[%s] failed: %v", searchResp.LogId, searchResp.Msg)
		return nil, err
	}

	res := make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
	for _, result := range searchResp.Data.WebPages.Value {
		// 接口中返回的值（例如：2025-02-23T08:18:30Z）实际上要表达的是 UTC+8 北京时间2025-02-23 08:18:30，并非UTC时间。这个问题将会在v2版本中修复。
		// 博查API 中 对于发布时间有bug 需要 先 -8小时
		publishTime := result.DateLastCrawled.Unix()
		publishTime = time.Unix(publishTime, 0).Add(-8 * time.Hour).Unix()
		res = append(res, &rpc.OutSiteSearchRecallAnswerResult{
			Name:          result.Name,
			Url:           result.URL,
			Snippet:       result.Snippet,
			Summary:       result.Summary,
			PublishedTime: publishTime,
		})
	}
	return res, nil
}
