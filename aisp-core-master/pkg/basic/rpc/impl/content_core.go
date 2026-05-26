package impl

import (
	"context"
	"sync"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content_angledless_view"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

const (
	sceneCode     = "AISP_CORE"
	bizCode       = "AISP_CORE"
	qaAiSceneCode = "ANSWER_AI_TAB"
	qaAiBizCode   = "ANSWER_AI_TAB"
	//qaAiSceneCode = "CONTENT_CORE"
	//qaAiBizCode   = "CONTENT_CORE"
)

type ContentCoreRpcImpl struct {
	contentServiceClient              *content.ContentServiceClient
	contentAnglelessViewServiceClient *content_angledless_view.ContentAnglelessViewServiceClient
}

var DefaultContentCoreRPCImpl rpc.ContentCoreRPC

func init() {
	DefaultContentCoreRPCImpl = NewContentCoreRPCImpl()
}

func NewContentCoreRPCImpl() *ContentCoreRpcImpl {
	return &ContentCoreRpcImpl{
		contentServiceClient: content.NewContentServiceClient(
			tzone.NewClient(
				"ContentService",
				tzone.Timeout(600*time.Millisecond),
				tzone.TargetName("content-core-rpc"),
			)),
		contentAnglelessViewServiceClient: content_angledless_view.NewContentAnglelessViewServiceClient(
			tzone.NewClient(
				"ContentAnglelessViewService",
				tzone.Timeout(600*time.Millisecond),
				tzone.TargetName("content-core-rpc"),
			)),
	}
}

// 接入文档：https://wiki.in.zhihu.com/pages/viewpage.action?pageId=260750816
func (r *ContentCoreRpcImpl) BatchGetContent(ctx context.Context, items []model.Content, withFields ...string) map[model.Content]*base.ContentInfo {
	result := make(map[model.Content]*base.ContentInfo)
	if items == nil || len(items) == 0 {
		return result
	}
	groupGetFunc := func(ids interface{}) interface{} {
		res := make(map[model.Content]*base.ContentInfo)

		realItems := ids.([]model.Content)
		var idItem []model.Content
		var tokenItem []model.Content
		for _, item := range realItems {
			if item.ContentID != 0 {
				idItem = append(idItem, item)
			} else if item.URLToken != "" {
				tokenItem = append(tokenItem, item)
			}
		}

		// 发起真实请求 并完成组合拼装
		getContentsById := r.batchGetContent(ctx, idItem, withFields)
		getContentsByToken := r.batchGetContentByToken(ctx, tokenItem, withFields)
		for k, v := range getContentsById {
			res[k] = v
		}
		for k, v := range getContentsByToken {
			res[k] = v
		}
		return res
	}
	safe_group.BatchGet(100, items, groupGetFunc, &result)
	return result
}

func (r *ContentCoreRpcImpl) batchGetContent(ctx context.Context, items []model.Content, withFields []string) map[model.Content]*base.ContentInfo {
	result := make(map[model.Content]*base.ContentInfo)
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "batchGetContent",
	})
	if items == nil || len(items) == 0 {
		return result
	}

	runFunc := func(ctx context.Context) error {
		outPairs := make([]*base.OutIDTypePair, 0, len(items))
		for _, realItem := range items {
			if contentCoreContentType := model.GetContentType(realItem.ContentType); contentCoreContentType != "UNKNOWN" {
				outPair := base.NewOutIDTypePair()
				outPair.Type = contentCoreContentType
				outPair.OutID = util.Int64String(realItem.ContentID)
				outPairs = append(outPairs, outPair)
			}
		}

		if len(outPairs) == 0 {
			return nil
		}

		param := &content.BatchGetContentWithFieldsByIdsAnglelessParam{
			BizCode:     bizCode,
			SceneCode:   sceneCode,
			ObjectInfos: outPairs,
			WithFields:  withFields,
		}

		log.Infof(ctx, "param:%s", util.GetJSONIgnoreError(param))

		response, err := r.contentServiceClient.BatchGetContentWithFieldsByIdsAngleless(ctx, param)
		if response == nil {
			logger.Errorf(ctx, "response nil")
			return err
		}
		for _, wContentWrapper := range response.GetContents() {
			contentInfo := wContentWrapper.GetContent()
			if contentInfo == nil {
				logger.Warn(ctx, "contentInfo nil")
				continue
			}
			itemId, transErr := util.String2Int64(contentInfo.OutID)
			if transErr != nil {
				logger.Errorf(ctx, "transErr:%v", transErr)
				continue
			}
			result[model.NewContentWithContentType(itemId, contentInfo.ContentType)] = contentInfo
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

func (r *ContentCoreRpcImpl) BatchGetContentByContentID(ctx context.Context, contentIds []string, withFields ...string) map[string]*base.ContentInfo {
	res := make(map[string]*base.ContentInfo)
	groupGetFunc := func(ids interface{}) interface{} {
		realIds := ids.([]string)
		return r.batchGetContentByContentID(ctx, realIds, withFields)
	}
	safe_group.BatchGet(100, contentIds, groupGetFunc, &res)
	return res
}

func (r *ContentCoreRpcImpl) batchGetContentByContentID(ctx context.Context, contentIds []string, withFields []string) map[string]*base.ContentInfo {
	res := make(map[string]*base.ContentInfo)
	runFunc := func(ctx context.Context) error {
		param := &content.BatchGetContentWithFieldsByIdsAnglelessParam{
			BizCode:    bizCode,
			SceneCode:  sceneCode,
			ContentIds: contentIds,
			WithFields: withFields,
		}

		result, err := r.contentServiceClient.BatchGetContentWithFieldsByIdsAngleless(ctx, param)
		if err == nil && result != nil {
			for _, wContentWrapper := range result.GetContents() {
				contentInfo := wContentWrapper.GetContent()
				if contentInfo == nil {
					continue
				}
				res[contentInfo.ID] = contentInfo
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func (r *ContentCoreRpcImpl) batchGetContentByToken(ctx context.Context, items []model.Content, withFields []string) map[model.Content]*base.ContentInfo {
	result := make(map[model.Content]*base.ContentInfo)
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "batchGetContentByToken",
	})
	if items == nil || len(items) == 0 {
		return result
	}

	runFunc := func(ctx context.Context) error {
		tokenPairs := make([]*base.UrlTokenTypePair, 0, len(items))
		for _, realItem := range items {
			if contentCoreContentType := model.GetContentType(realItem.ContentType); contentCoreContentType != "UNKNOWN" {
				tokenPair := base.NewUrlTokenTypePair()
				tokenPair.URLToken = realItem.URLToken
				tokenPair.Type = model.GetContentType(realItem.ContentType)
				tokenPairs = append(tokenPairs, tokenPair)
			}
		}

		if len(tokenPairs) == 0 {
			return nil
		}

		param := &content.BatchGetContentWithFieldsByIdsAnglelessParam{
			BizCode:       bizCode,
			SceneCode:     sceneCode,
			URLTokenInfos: tokenPairs,
			WithFields:    withFields,
		}

		response, err := r.contentServiceClient.BatchGetContentWithFieldsByIdsAngleless(ctx, param)
		if response == nil {
			logger.Errorf(ctx, "response nil")
			return err
		}
		for _, wContentWrapper := range response.GetContents() {
			contentInfo := wContentWrapper.GetContent()
			if contentInfo == nil {
				logger.Errorf(ctx, "contentInfo nil")
				continue
			}

			if contentInfo.GetDetail().GetURLToken() == "" {
				logger.Errorf(ctx, "url token nil")
				continue
			}
			result[model.NewContentWithToken(contentInfo.GetDetail().GetURLToken(), contentInfo.ContentType)] = contentInfo
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

func (r *ContentCoreRpcImpl) BatchGetStructuredSegmentsByContentIDs(ctx context.Context, contentId model.Content, paragraphs []*proto.DocQaExtraParagraphInfo, withFields ...string) []*rpc.ParagraphExpansionWord {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "BatchGetStructuredSegmentsByContentIDs",
	})

	// 处理offset信息
	offsetArr := lo.Map(paragraphs, func(item *proto.DocQaExtraParagraphInfo, index int) int64 {
		return item.GetParagraphIndex()
	})
	beginOffset := lo.Min(offsetArr)
	endOffset := lo.Max(offsetArr)
	if endOffset <= beginOffset {
		endOffset = beginOffset + 1
	}

	pWords := make([]*rpc.ParagraphExpansionWord, 0)
	runFunc := func(ctx context.Context) error {
		outPair := base.NewOutIDTypePair()
		outPair.Type = contentId.GetContentType()
		outPair.OutID = util.Int64String(contentId.ContentID)
		param := &content.BatchGetStructuredSegmentsByIdsParam{
			BizCode:     qaAiBizCode,
			SceneCode:   qaAiSceneCode,
			StartOffset: beginOffset,
			EndOffset:   endOffset,
			ObjectInfos: []*base.OutIDTypePair{outPair},
			WithFields:  withFields,
		}
		response, err := r.contentServiceClient.BatchGetStructuredSegmentsByIds(ctx, param)
		for _, wContentWrapper := range response.GetContentContainer() {
			structuredDoc := wContentWrapper.GetStructuredDoc()
			if structuredDoc == nil {
				logger.Errorf(ctx, "structuredDoc nil")
				continue
			}

			segments := structuredDoc.GetSegments()
			if segments == nil {
				continue
			}

			for _, segment := range segments {
				marks := segment.GetParagraph().GetMarks()
				if marks == nil {
					continue
				}
				for _, mark := range marks {
					words := mark.GetParagraphExpansionWords()
					if words == nil {
						continue
					}
					relWords := words.GetWords()
					if relWords == nil {
						continue
					}

					for _, w := range relWords {
						pWords = append(pWords, &rpc.ParagraphExpansionWord{
							Word: w.GetWord(),
							ID:   w.GetID(),
						})
					}
				}
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return pWords
}

func (r *ContentCoreRpcImpl) BatchGetContentPaperByOutSiteTypeId(ctx context.Context, papers []rpc.OutSitePaper) map[rpc.OutSitePaper]*model.Content {
	resultMap := sync.Map{}
	group := safe_group.NewGroupWithTimeout("BatchGetContentPaperByOutSiteTypeId", 2000).SetLimit(100)
	for _, paper := range papers {
		paper := paper
		group.Go(func() error {
			rpcRes := r.doGetContentPaperByOutSiteTypeId(ctx, paper)
			if rpcRes != nil {
				resultMap.Store(paper, r.doGetContentPaperByOutSiteTypeId(ctx, paper))
			}
			return nil
		})
	}
	_ = group.Wait()
	result := make(map[rpc.OutSitePaper]*model.Content)
	for _, paper := range papers {
		if res, ok := resultMap.Load(paper); ok {
			result[paper] = res.(*model.Content)
		}
	}
	return result
}

func (r *ContentCoreRpcImpl) doGetContentPaperByOutSiteTypeId(ctx context.Context, paper rpc.OutSitePaper) *model.Content {
	var contentModel *model.Content
	runFunc := func(ctx context.Context) error {
		contentResp, err := r.contentAnglelessViewServiceClient.GetContentIDByExternalID(ctx, &content_angledless_view.GetContentIDByExternalIDParam{
			ExternalID: paper.OutId,
			DataSource: string(paper.PaperType),
		})
		if err != nil || contentResp.GetError() != nil {
			return err
		}
		if contentResp.GetID() != "" {
			docId, docIdErr := cast.ToInt64E(contentResp.GetID())
			if docIdErr != nil {
				return docIdErr
			}
			withContentType := model.NewContentWithContentType(docId, contentResp.GetType())
			contentModel = &withContentType
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return contentModel
}

var _ rpc.ContentCoreRPC = (*ContentCoreRpcImpl)(nil)
