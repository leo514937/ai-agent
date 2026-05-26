package meta_fetcher

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"regexp"
	"strings"
	"sync"
	"time"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/document_parse"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	util2 "git.in.zhihu.com/zrec/zrec-utils/util"
)

// @logicAuthor: wangran
// @logicInfo: 获取内容 document 信息

type DocumentFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, []*model.DocumentParagraph]
	documentParseService service.DocumentParseService
}

func NewDocumentFetcherLogic(name string, config map[string]string) *DocumentFetcherLogic {
	res := &DocumentFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, []*model.DocumentParagraph](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.documentParseService = service.DefaultDocumentParseService
	return res
}

func (d *DocumentFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]*model.DocumentParagraph, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.DocumentFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	logger := log.WithFields(ctx, map[string]any{
		"func": "DocumentFetcherLogic.fetch",
	})

	resMap := make(map[data_frame.UniqueId][]*model.DocumentParagraph)

	if items == nil || len(items) == 0 {
		return resMap, nil
	}

	group := safe_group.NewGroupWithTimeout("DocumentFetcherLogic", 2000).SetLimit(10)
	var resultMap sync.Map

	for _, item := range items {
		group.Go(func() error {
			var documentParagraphs []*model.DocumentParagraph
			itemMeta := item.GetBizItem().GetItemMeta()
			if itemMeta.DocType == content.DocType_Answer || itemMeta.DocType == content.DocType_Article {
				if itemMeta.ContentInfo.GetContentBody() != nil {
					parseResult := d.documentParseService.GetHtmlParsingElement(ctx, itemMeta.ContentInfo.GetContentBody().GetBody(), rpc.ProcessorNameLocalHtmlParser, true)
					if parseResult != nil {
						for _, block := range parseResult.Blocks {
							blockId, err := util2.String2Int(block.ID)
							if err == nil {
								documentParagraphs = append(documentParagraphs, &model.DocumentParagraph{
									ID:      blockId,
									Content: block.Content,
								})
							}
						}
					}
				}
			}
			resultMap.Store(*data_frame.NewUniqueId(item.GetCommonItem().Id()), documentParagraphs)
			return nil
		})
	}

	// 等待所有并发调用完成
	if err := group.Wait(); err != nil {
		logger.Errorf(ctx, "DocumentFetcherLogic concurrent calls failed: %v", err)
	}

	for _, item := range items {
		uniqueId := *data_frame.NewUniqueId(item.GetCommonItem().Id())
		paragraphs, isOk := resultMap.Load(uniqueId)
		if isOk {
			resMap[uniqueId] = paragraphs.([]*model.DocumentParagraph)
		} else {
			resMap[uniqueId] = nil
		}
	}

	logger.Infof(ctx, "fetch completed, processed %d items, got %d responses", len(items), len(resMap))
	return resMap, nil
}

func (d *DocumentFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res []*model.DocumentParagraph) error {
	document := &model.Document{}

	// 设置标题（answer取问题的标题）
	document.Title = item.GetBizItem().GetItemMeta().GetTitle()
	if item.GetBizItem().GetItemMeta().DocType != content.DocType_ZhiDaUserUpload {
		document.AuthorName = item.GetBizItem().GetItemMeta().AuthorName
	}

	// 设置段落信息
	document.Paragraphs = res

	// 设置摘要（清理换行）
	contentInfo := item.GetBizItem().GetItemMeta().ContentInfo
	if contentInfo != nil {
		if contentInfo.Summary != nil && *contentInfo.Summary != "" {
			// 清理摘要中的换行符
			abstract := cleanNewlines(*contentInfo.Summary)
			if abstract != "" {
				document.Abstract = abstract
			}
		}
	}

	// 根据文档类型处理其余字段
	switch item.GetBizItem().GetItemMeta().DocType {
	case content.DocType_Webpage:
		d.processWebpageDocument(ctx, document, item.GetBizItem().GetItemMeta())
	case content.DocType_Paper:
		d.processPaperDocument(ctx, document, item.GetBizItem().GetItemMeta())
	case content.DocType_Answer, content.DocType_Article:
		d.processZhihuDocument(ctx, document, item.GetBizItem().GetItemMeta())
	case content.DocType_ZhiDaUserUpload:
		d.processDocumentDocument(ctx, document, item.GetBizItem().GetItemMeta())
	default:
		document.Sources = strings.Join(item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Source, ",")
		if document.Paragraphs == nil {
			paragraphs := parseTextToParagraphs(item.GetBizItem().GetItemMeta().Content)
			document.Paragraphs = paragraphs
		}
		if item.GetBizItem().ItemMeta.PublishedTime != 0 {
			dateStr := time.Unix(item.GetBizItem().ItemMeta.PublishedTime, 0).Format("20060102")
			document.DatePublished = dateStr
		}
	}

	item.GetBizItem().GetItemMeta().Document = document

	return nil
}

// processWebpageDocument 处理网页类型文档
func (d *DocumentFetcherLogic) processWebpageDocument(ctx context.Context, document *model.Document, itemMeta *model.ItemMeta) {
	contentInfo := itemMeta.ContentInfo
	if contentInfo != nil && contentInfo.BizExtDetail != nil && contentInfo.BizExtDetail.ExternalWebpageBizExt != nil {
		detail := contentInfo.BizExtDetail.ExternalWebpageBizExt

		// 设置作者和URL
		if detail.Author != "" {
			document.AuthorName = detail.Author
		}
		if detail.URL != "" {
			document.URL = detail.URL
		}

		// 构建来源列表
		sources := itemMeta.GetRecallSourceInfo().Source
		if detail.URL != "" {
			if parsedURL, err := url.Parse(detail.URL); err == nil {
				sources = append(sources, fmt.Sprintf("domain:%s", parsedURL.Hostname()))
			}
		}

		document.Sources = strings.Join(sources, ",")

		// 解析段落
		if document.Paragraphs == nil {
			paragraphs := parseTextToParagraphs(itemMeta.Content)
			document.Paragraphs = paragraphs
		}
	}
}

// processPaperDocument 处理论文类型文档
func (d *DocumentFetcherLogic) processPaperDocument(ctx context.Context, document *model.Document, itemMeta *model.ItemMeta) {
	// 解析业务扩展信息
	var bizExt map[string]interface{}
	contentInfo := itemMeta.ContentInfo
	if contentInfo.BizExt != nil && *contentInfo.BizExt != "" {
		if err := json.Unmarshal([]byte(*contentInfo.BizExt), &bizExt); err == nil {
			// 设置作者姓名
			if author, ok := bizExt["writer"].(string); ok && author != "" {
				author = cleanNewlinesAndSpaces(author)
				document.AuthorName = author
			}

			// 设置发布日期
			if publishDate, ok := bizExt["publish_date"].(string); ok {
				document.DatePublished = publishDate
			}

			// 构建来源列表
			sources := itemMeta.GetRecallSourceInfo().Source

			if sourceVal, ok := bizExt["source"].(string); ok {
				if strings.ToLower(sourceVal) == "arxiv" {
					sources = append(sources, "domain:arxiv.org")
					// 构建arXiv URL
					if id, ok := bizExt["ID"].(string); ok {
						if versions, ok := bizExt["versions"].([]interface{}); ok && len(versions) > 0 {
							lastVersion := versions[len(versions)-1]
							document.URL = fmt.Sprintf("https://arxiv.org/abs/%s%s", id, lastVersion)
						}
					}
				} else {
					sources = append(sources, "domain:维普论文")
				}
			}

			// 添加期刊信息
			if journal, ok := bizExt["journal"].(string); ok && journal != "" {
				sources = append(sources, fmt.Sprintf("journal:%s", journal))
			}

			document.Sources = strings.Join(sources, ",")
		}
	}

	// 解析段落
	if document.Paragraphs == nil {
		paragraphs := parseTextToParagraphs(itemMeta.Content)
		document.Paragraphs = paragraphs
	}
}

// processZhihuDocument 处理知乎类型文档（回答和文章）
func (d *DocumentFetcherLogic) processZhihuDocument(ctx context.Context, document *model.Document, itemMeta *model.ItemMeta) {
	contentInfo := itemMeta.ContentInfo
	contentStats := itemMeta.Statistics

	// 构建来源列表
	sources := itemMeta.GetRecallSourceInfo().Source
	sources = append(sources, "domain:知乎")
	document.Sources = strings.Join(sources, ",")

	// 设置作者ID和URL
	if contentInfo.AuthorID != 0 {
		document.AuthorID = contentInfo.AuthorID
	}

	if contentInfo.ExtInfo != nil && contentInfo.ExtInfo.URL != nil && *contentInfo.ExtInfo.URL != "" {
		document.URL = *contentInfo.ExtInfo.URL
	}

	// 设置发布日期
	if contentInfo.Published != 0 {
		dateStr := time.Unix(contentInfo.Published, 0).Format("20060102")
		document.DatePublished = dateStr
	}

	// 解析正文内容
	if contentInfo.ContentBody != nil && contentInfo.ContentBody.Body != "" {
		text := strings.TrimSpace(contentInfo.ContentBody.Body)
		if text != "" {
			// 这里需要实现parse_markdown和markdownify的等效功能
			// 暂时使用简单的HTML到文本转换
			cleanText, _ := util.ContentHtml2Markdown(ctx, text)
			if document.Paragraphs == nil {
				paragraphs := parseTextToParagraphs(cleanText)
				document.Paragraphs = paragraphs
			}
		}
	}

	// 设置统计信息
	if contentStats != nil {
		stats := make(map[string]interface{})

		// 设置点赞数
		if upVoteCount := contentStats.GetUpVoteCount(); upVoteCount > 0 {
			stats["点赞数"] = upVoteCount
		}

		// 设置收藏数
		if favorites := contentStats.GetFavorites(); favorites > 0 {
			stats["收藏数"] = favorites
		}

		// 设置评论数
		if commentCount := contentStats.GetCommentCount(); commentCount > 0 {
			stats["评论数"] = commentCount
		}

		// 设置分享数
		if shareCount := contentStats.GetShareCount(); shareCount > 0 {
			stats["分享数"] = shareCount
		}

		// 只有当有统计信息时才设置
		if len(stats) > 0 {
			document.Stats = stats
		}
	}
}

// processDocumentDocument 处理文档类型
func (d *DocumentFetcherLogic) processDocumentDocument(ctx context.Context, document *model.Document, itemMeta *model.ItemMeta) {
	contentInfo := itemMeta.ContentInfo

	// 构建来源列表
	sources := itemMeta.GetRecallSourceInfo().Source

	if contentInfo.ExtInfo != nil && contentInfo.ExtInfo.URL != nil && *contentInfo.ExtInfo.URL != "" {
		document.URL = *contentInfo.ExtInfo.URL
		if parsedURL, err := url.Parse(*contentInfo.ExtInfo.URL); err == nil {
			sources = append(sources, fmt.Sprintf("domain:%s", parsedURL.Hostname()))
		}
	}

	document.Sources = strings.Join(sources, ",")

	// 解析段落
	if document.Paragraphs == nil {
		paragraphs := parseTextToParagraphs(itemMeta.Content)
		document.Paragraphs = paragraphs
	}
}

// cleanNewlines 清理换行符，对应Python代码中的re.sub(r"[\n\r]+", " ", text)
func cleanNewlines(text string) string {
	re := regexp.MustCompile(`[\n\r]+`)
	return re.ReplaceAllString(text, " ")
}

// cleanNewlinesAndSpaces 清理换行符和多余空格，对应Python代码中的re.sub(r"[\n\r ]+", " ", text)
func cleanNewlinesAndSpaces(text string) string {
	re := regexp.MustCompile(`[\n\r ]+`)
	return re.ReplaceAllString(text, " ")
}

// parseTextToParagraphs 将文本分割为段落，对应Python代码中的段落分割逻辑
func parseTextToParagraphs(text string) []*model.DocumentParagraph {
	if text == "" {
		return nil
	}

	// 按换行符分割
	lines := strings.Split(strings.TrimSpace(text), "\n")
	var paragraphs []*model.DocumentParagraph

	for i, line := range lines {
		line = strings.TrimSpace(line)
		if line != "" {
			paragraphs = append(paragraphs, &model.DocumentParagraph{
				ID:      i,
				Content: line,
			})
		}
	}

	return paragraphs
}
