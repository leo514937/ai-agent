package meta_fetcher

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service2 "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/document_parse"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/personal_knowledge_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 获取内部文档 meta 信息

type InternalDocMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, *DocumentMeta]
	internalKnowledgeBaseService service.InternalKnowledgeBaseService
	documentParseService         service2.DocumentParseService
}

func NewInternalDocMetaFetcherLogic(name string, config map[string]string) *InternalDocMetaFetcherLogic {
	res := &InternalDocMetaFetcherLogic{
		FetcherLogic:                 fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, *DocumentMeta](name, config),
		internalKnowledgeBaseService: service.NewInternalKnowledgeBaseServiceImpl(),
		documentParseService:         service2.DefaultDocumentParseService,
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	return res
}

type DocumentMeta struct {
	documentInfo *model.DocumentInfo
	element      *model.Element
}

func (i *InternalDocMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*DocumentMeta, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.ContentCoreMetaFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	var resMap = make(map[data_frame.UniqueId]*DocumentMeta)

	internalDocs := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], _ int) bool {
		return item.GetBizItem().GetItemMeta().DocType == content.DocType_InternalDoc ||
			item.GetBizItem().GetItemMeta().DocType == content.DocType_AispUserUpload
	})

	if len(internalDocs) == 0 {
		return resMap, nil
	}

	contents := make([]model.Content, 0)
	for _, internalDoc := range internalDocs {
		result := &DocumentMeta{}
		result.documentInfo = i.internalKnowledgeBaseService.GetDocumentInfo(ctx, internalDoc.GetBizItem().GetItemMeta().DocId, internalDoc.GetBizItem().GetItemMeta().DocType)

		// 对于 pdf 文档，需要读取文件解析表，拿到解析结果
		if result.documentInfo.DocSubtype == model.DocSubtypePdf {
			var element *model.Element
			element = i.documentParseService.GetDocumentParsingElement(ctx, internalDoc.GetBizItem().GetItemMeta().DocId, internalDoc.GetBizItem().GetItemMeta().DocType, rpc.ProcessorNameVisionPdfParser)
			if element == nil {
				element = i.documentParseService.GetDocumentParsingElement(ctx, internalDoc.GetBizItem().GetItemMeta().DocId, internalDoc.GetBizItem().GetItemMeta().DocType, rpc.ProcessorNameRulePdfParser)
			}
			result.element = element
		}

		resMap[*data_frame.NewUniqueId(internalDoc.GetCommonItem().Id())] = result
		contents = append(contents, model.NewContentWithDocType(internalDoc.GetBizItem().GetItemMeta().DocId, internalDoc.GetBizItem().GetItemMeta().DocType))
	}

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(contents))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(resMap))
	return resMap, nil
}

func (i *InternalDocMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *DocumentMeta) error {
	if res == nil || res.documentInfo == nil {
		return nil
	}
	item.GetBizItem().GetItemMeta().Title = res.documentInfo.Title
	item.GetBizItem().GetItemMeta().Abstract = res.documentInfo.Abstract
	item.GetBizItem().GetItemMeta().Content = res.documentInfo.Content
	item.GetBizItem().GetItemMeta().Url = res.documentInfo.Url
	item.GetBizItem().GetItemMeta().AuthorityLevel = proto.AuthorityLevel(proto.AuthorityLevel_value[res.documentInfo.AuthorityLevel])
	item.GetBizItem().GetItemMeta().PublishedTime = res.documentInfo.LastUpdatedTime
	if res.element != nil {
		item.GetBizItem().GetItemMeta().DocumentParsing = res.element
		item.GetBizItem().GetItemMeta().Content = res.element.Text
	}

	return nil
}
