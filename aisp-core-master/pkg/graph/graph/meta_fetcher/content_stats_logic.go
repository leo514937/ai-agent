package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-content_prod/content_prod_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 获取内容的实时互动统计

type ContentStatsFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, *content.ContentStatistics]
	contentProdRpc rpc.ContentProdRPC
}

func NewContentStatsFetcherLogic(name string, config map[string]string) *ContentStatsFetcherLogic {
	res := &ContentStatsFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, *content.ContentStatistics](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.contentProdRpc = impl.NewContentProdRPCImpl()
	return res
}

func (c *ContentStatsFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*content.ContentStatistics, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.TagCoreMetaFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]*content.ContentStatistics)

	var contents []model.Content
	for _, item := range items {
		contents = append(contents, model.NewContentWithDocType(item.GetBizItem().GetItemMeta().DocId, item.GetBizItem().GetItemMeta().DocType))
	}

	contentStatisticMap := c.contentProdRpc.BatchGetContent(ctx, contents, &content.WithFieds{
		StatisticsFields: &content.StatisticsFields{
			AllStatistics: lo.ToPtr(true),
		},
	})

	for _, item := range items {
		eachContent := model.NewContentWithDocType(item.GetBizItem().GetItemMeta().DocId, item.GetBizItem().GetItemMeta().DocType)
		if profile, exist := contentStatisticMap[eachContent]; exist {
			resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = profile.GetContentStatistics()
		}
	}

	constant.DataOutputNodeLog.Infof(logCtx, "%v", "")
	return resMap, nil
}

func (c *ContentStatsFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *content.ContentStatistics) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.TagCoreMetaFetcherLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetItemMeta().Statistics = res
	return nil
}
