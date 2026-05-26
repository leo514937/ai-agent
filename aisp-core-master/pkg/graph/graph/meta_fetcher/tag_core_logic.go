package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	content2 "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: liupenghe
// @logicInfo: 获取内容的 tag 标识

type TagCoreMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]*tag_core.Tags]
	tagCoreRpc rpc.TagCoreGRPC
}

func NewTagCoreMetaFetcherLogic(name string, config map[string]string) *TagCoreMetaFetcherLogic {
	res := &TagCoreMetaFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]*tag_core.Tags](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.tagCoreRpc = impl.DefaultTagGrpcImpl
	return res
}

func (c *TagCoreMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]map[string]*tag_core.Tags, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.TagCoreMetaFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	sceneCode := rpc.SceneCode(requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.TagCoreSceneCode))
	appGroupCode := rpc.AppGroupCode(requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.TagCoreAppGroupCode))

	resMap := make(map[data_frame.UniqueId]map[string]*tag_core.Tags)

	if sceneCode == "" || appGroupCode == "" {
		return resMap, nil
	}

	var contents []model.Content
	for _, item := range items {
		docId := item.GetBizItem().GetItemMeta().DocId
		docType := item.GetBizItem().GetItemMeta().DocType
		urlToken := item.GetBizItem().GetItemMeta().UrlToken
		if docId != 0 && docType != content2.DocType_Unknown {
			contents = append(contents, model.NewContent(docId, docType, urlToken))
		}
	}

	if len(contents) == 0 {
		return resMap, nil
	}

	tagMap := c.tagCoreRpc.BatchGetTag(ctx, sceneCode, appGroupCode, contents)

	for _, item := range items {
		content := model.NewContent(item.GetBizItem().GetItemMeta().DocId, item.GetBizItem().GetItemMeta().DocType, item.GetBizItem().GetItemMeta().UrlToken)
		if tagProfile, exist := tagMap[content]; exist {
			resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = tagProfile.GetTags()
		}
	}

	constant.DataOutputNodeLog.Infof(logCtx, "%v", "")

	return resMap, nil
}

func (c *TagCoreMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res map[string]*tag_core.Tags) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.TagCoreMetaFetcherLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetItemMeta().TagInfo = res
	return nil
}
