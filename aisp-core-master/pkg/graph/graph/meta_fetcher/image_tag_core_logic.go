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

// @logicAuthor: wangran
// @logicInfo: 获取内容里的图片的 tagcore 标签

type ImageTagCoreMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]map[string]*tag_core.Tags]
	tagCoreRpc rpc.TagCoreGRPC
}

func NewImageTagCoreMetaFetcherLogic(name string, config map[string]string) *ImageTagCoreMetaFetcherLogic {
	res := &ImageTagCoreMetaFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]map[string]*tag_core.Tags](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.tagCoreRpc = impl.DefaultTagGrpcImpl
	return res
}

func (c *ImageTagCoreMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]map[string]map[string]*tag_core.Tags, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.TagCoreMetaFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	sceneCode := rpc.SceneCode(requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.TagCoreSceneCode))
	appGroupCode := rpc.AppGroupCode(requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.TagCoreAppGroupCode))

	resMap := make(map[data_frame.UniqueId]map[string]map[string]*tag_core.Tags)

	if sceneCode == "" || appGroupCode == "" {
		return resMap, nil
	}

	var imageKeys []model.Content
	for _, item := range items {
		for _, image := range item.GetBizItem().GetItemMeta().Images {
			imageKeys = append(imageKeys, model.NewContent(0, content2.DocType_Image, image.ImgToken))
		}
	}

	if len(imageKeys) == 0 {
		return resMap, nil
	}

	tagMap := c.tagCoreRpc.BatchGetTag(ctx, sceneCode, appGroupCode, imageKeys)

	for _, item := range items {
		resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = make(map[string]map[string]*tag_core.Tags)
		for _, image := range item.GetBizItem().GetItemMeta().Images {
			imageKey := model.NewContent(0, content2.DocType_Image, image.ImgToken)
			if tagProfile, exist := tagMap[imageKey]; exist {
				resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())][image.ImgToken] = tagProfile.GetTags()
			}
		}
	}

	constant.DataOutputNodeLog.Infof(logCtx, "%v", "")

	return resMap, nil
}

func (c *ImageTagCoreMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res map[string]map[string]*tag_core.Tags) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.TagCoreMetaFetcherLogic.itemMerge")
	defer span.Finish()

	for _, image := range item.GetBizItem().GetItemMeta().Images {
		image.TagInfo = res[image.ImgToken]
	}

	return nil
}
