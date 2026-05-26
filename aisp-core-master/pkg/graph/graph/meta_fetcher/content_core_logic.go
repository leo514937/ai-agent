package meta_fetcher

import (
	"context"
	"strings"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/document_parse"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 获取内容 meta 信息

type ContentCoreMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, *contentMetaResult]
	documentParseService service.DocumentParseService
	contentCoreRpc       rpc.ContentCoreRPC
	ossClient            rpc.Oss
	doubleCheckTypes     []aiContent.DocType_Type
}

func NewContentCoreMetaFetcherLogic(name string, config map[string]string) *ContentCoreMetaFetcherLogic {
	res := &ContentCoreMetaFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, *contentMetaResult](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.documentParseService = service.DefaultDocumentParseService
	res.contentCoreRpc = impl.DefaultContentCoreRPCImpl
	res.ossClient = impl.DefaultOssImpl
	res.doubleCheckTypes = []aiContent.DocType_Type{aiContent.DocType_Webpage, aiContent.DocType_CrawlerWebpage}
	return res
}

type contentMetaResult struct {
	contentInfo *base.ContentInfo
	element     *model.Element
	text        string
}

func (c *ContentCoreMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*contentMetaResult, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.ContentCoreMetaFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	logger := log.WithFields(ctx, map[string]any{
		"func": "ContentCoreMetaFetcherLogic-realRecallConvert",
	})
	logger.Debugf(ctx, "do running")

	if items == nil || len(items) == 0 {
		return map[data_frame.UniqueId]*contentMetaResult{}, nil
	}

	resMap := make(map[data_frame.UniqueId]*contentMetaResult)
	itemMap := make(map[model.Content]*data_frame.ItemData[entities.Item])
	contents := make([]model.Content, 0)
	for _, contentItem := range items {
		docId := contentItem.GetBizItem().GetItemMeta().DocId
		urlToken := contentItem.GetBizItem().GetItemMeta().UrlToken
		docType := contentItem.GetBizItem().GetItemMeta().DocType

		// 只针对站内内容，获取 contentInfo
		if docType == content.DocType_Unknown || docType == content.DocType_Text || docType == content.DocType_Link ||
			docType == content.DocType_InternalDoc || docType == content.DocType_AispUserUpload || (docId == 0 && urlToken == "") {
			continue
		}

		newContent := model.Content{
			ContentID:   docId,
			URLToken:    urlToken,
			ContentType: docType,
		}

		contents = append(contents, newContent)
		itemMap[newContent] = contentItem
	}

	// 查询内容 url token
	contentResultMap := c.contentCoreRpc.BatchGetContent(ctx, contents,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody,
		base.ContentInfoFieldContentBizExtDetail,
		base.ContentInfoFieldContentBizExt,
		base.ContentInfoFieldContentMediaDetail,
		base.ContentInfoFieldContentSummary)

	// check一下 其他业务 有没有知乎召回的内容，如果有，删除，重新召回
	deleteContents := make([]model.Content, 0)
	deleteContentKeyMap := make(map[model.Content]model.Content)
	reTryContents := make([]model.Content, 0)
	for k, v := range contentResultMap {
		if v == nil || !lo.Contains(c.doubleCheckTypes, k.GetDocType()) || !strings.Contains(v.GetBizExt(), "url") {
			continue
		}
		bizExt := &BizExt{}
		err := util.JSONUnmarshal([]byte(v.GetBizExt()), bizExt)
		if err != nil {
			continue
		}
		linkType, subType, token := util.ParseLinkInfo(bizExt.Url)
		// 判断是否知乎召回
		if linkType == util.LinkTypeZhihu && token != "" {
			deleteContents = append(deleteContents, k)
			deleteContentKeyMap[k] = model.NewContentWithToken(token, subType)
			reTryContents = append(reTryContents, deleteContentKeyMap[k])
		}
	}
	for _, k := range deleteContents {
		delete(contentResultMap, k)
	}
	reTryContentResultMap := c.contentCoreRpc.BatchGetContent(ctx, reTryContents,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody,
		base.ContentInfoFieldContentBizExtDetail,
		base.ContentInfoFieldContentBizExt,
		base.ContentInfoFieldContentMediaDetail,
		base.ContentInfoFieldContentSummary)
	contentResultMap = util.OverrideMap(contentResultMap, reTryContentResultMap)

	//	获取内容 ContentCoreInfo
	for k, v := range itemMap {
		contentInfo, isOk := contentResultMap[k]
		if !isOk {
			// 查一次 看看是否是站外转站内
			contentInfo, isOk = contentResultMap[deleteContentKeyMap[k]]
			if !isOk {
				if k.ContentType == content.DocType_ZhiDaUserUpload {
					util.Increment(ctx, macro.CommonStatsPrefix+".user_upload.empty_content.count")
				}
				continue
			}
		}

		resMap[*data_frame.NewUniqueId(v.GetCommonItem().Id())] = &contentMetaResult{
			contentInfo: contentInfo,
		}
	}
	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(contents))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(resMap))

	// 并发处理文档解析
	if len(items) > 0 {
		// 创建并发组
		group := safe_group.NewGroupWithTimeout("ContentCoreMetaFetcherLogic", 10000).SetLimit(200)

		// 创建结果通道
		resultChan := make(chan struct {
			itemKey data_frame.UniqueId
			element *model.Element
			text    string
		}, len(items))

		// 并发处理每个item的文档解析
		for _, item := range items {
			group.Go(func() error {
				defer func() {
					if r := recover(); r != nil {
						log.Warnf(ctx, "ContentCoreMetaFetcherLogic Parse Panic => %v", r)
					}
				}()

				itemKey := *data_frame.NewUniqueId(item.GetCommonItem().Id())
				if res, ok := resMap[itemKey]; ok && res.contentInfo != nil {
					var element *model.Element
					var text string

					// 维普 arxiv 的 pdf
					if item.GetBizItem().GetItemMeta().DocType == content.DocType_Paper {
						element, text = c.documentParseService.PaperParse(ctx, res.contentInfo)
					}

					// 用户上传
					if item.GetBizItem().GetItemMeta().DocType == content.DocType_ZhiDaUserUpload {
						element, text, _ = c.documentParseService.UserUploadParse(ctx, res.contentInfo)
					}

					// 个人知识库订阅流
					if res.contentInfo.GetBizExtDetail() != nil && res.contentInfo.GetBizExtDetail().GetExternalWebpageBizExt() != nil {
						_, text = c.documentParseService.RssParse(ctx, res.contentInfo)
					}

					// 图文类型
					if res.contentInfo.GetContentBody() != nil {
						// 清洗正文
						body := res.contentInfo.GetContentBody().GetBody()
						filteredBody, err := util.ContentHtml2Markdown(ctx, body)
						if err == nil {
							text = filteredBody
						}
					}

					// 发送结果到通道
					resultChan <- struct {
						itemKey data_frame.UniqueId
						element *model.Element
						text    string
					}{
						itemKey: itemKey,
						element: element,
						text:    text,
					}
				}

				return nil
			})
		}

		// 等待所有 goroutine 完成并关闭通道
		go func() {
			wgErr := group.Wait()
			if wgErr != nil {
				log.Errorf(ctx, "ContentCoreMetaFetcherLogic Parse Wait Err => %v", wgErr)
			}
			close(resultChan)
		}()

		// 收集结果并更新 resMap
		for result := range resultChan {
			if res, ok := resMap[result.itemKey]; ok {
				res.element = result.element
				res.text = result.text
			}
		}
	}

	return resMap, nil
}

func (c *ContentCoreMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *contentMetaResult) error {
	if res == nil || res.contentInfo == nil {
		return nil
	}
	logger := log.WithFields(ctx, map[string]any{
		"func": "ContentCoreMetaFetcherLogic-itemMerge",
	})

	contentInfo := res.contentInfo
	if contentInfo.GetContentBody() == nil && contentInfo.GetMediaDetail() == nil {
		logger.Warnf(ctx, "res content body is nil => : %s", util.GetJSONIgnoreError(res))
		return nil
	}

	docId, err := cast.ToInt64E(contentInfo.GetOutID())
	if err != nil {
		logger.Errorf(ctx, "cast to int64 error: %v", err)
		return nil
	}

	// 一些属性信息
	item.GetBizItem().GetItemMeta().PublishedTime = contentInfo.Published

	// 如果是 paper 类型需要去取 paper的 时间
	if contentInfo.GetBizExtDetail() != nil && contentInfo.GetBizExtDetail().GetPaperBizExt() != nil {
		if time, tErr := util.StringDate2Time(contentInfo.GetBizExtDetail().GetPaperBizExt().GetPublishDate()); tErr == nil {
			item.GetBizItem().GetItemMeta().PublishedTime = time.Unix()
		}
	}

	// 站内文档 查询URL
	if contentInfo.GetExtInfo() != nil {
		item.GetBizItem().GetItemMeta().Url = contentInfo.GetExtInfo().GetURL()
	}

	item.GetBizItem().GetItemMeta().ContentInfo = contentInfo
	item.GetBizItem().GetItemMeta().DocId = docId
	if item.GetBizItem().GetItemMeta().Title == "" {
		item.GetBizItem().GetItemMeta().Title = contentInfo.GetTitle()
	}
	item.GetBizItem().GetItemMeta().Abstract = contentInfo.GetSummary()
	item.GetBizItem().GetItemMeta().AuthorId = contentInfo.GetAuthorID()

	item.GetBizItem().GetItemMeta().DocumentParsing = res.element
	item.GetBizItem().GetItemMeta().Content = res.text

	// 图片
	if contentInfo.GetContentBody() != nil {
		body := contentInfo.GetContentBody().GetBody()
		item.GetBizItem().GetItemMeta().Images = model.ParseImageInfos(body)
	}

	// 上传文件类型，但是没有解析结果，打点
	if item.GetBizItem().GetItemMeta().DocType == content.DocType_ZhiDaUserUpload && item.GetBizItem().GetItemMeta().DocumentParsing == nil {
		util.Increment(ctx, macro.CommonStatsPrefix+".user_upload.empty_content.count")
	}

	// 如果内容为空 摘要不为空，则使用摘要作为内容
	if item.GetBizItem().GetItemMeta().Content == "" && item.GetBizItem().GetItemMeta().Abstract != "" {
		item.GetBizItem().GetItemMeta().Content = item.GetBizItem().GetItemMeta().Abstract
		util.Increment(ctx, macro.CommonStatsPrefix+".abs_compensate.empty_content.count")
	}
	return nil
}

type BizExt struct {
	Url string `json:"url"`
}
