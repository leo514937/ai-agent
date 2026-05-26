package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/klara_model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type SearchIntentionLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, macro.IntentionType]
	klaraService klara_model.KlaraModelService
}

func NewSearchIntentionLogic(name string, config map[string]string) *SearchIntentionLogic {
	res := &SearchIntentionLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, macro.IntentionType](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.klaraService = klara_model.NewKlaraModelServiceImpl()
	return res
}

func (s *SearchIntentionLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]macro.IntentionType, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.SearchIntentionLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]macro.IntentionType)

	// items 为 queryMerge 的结果，长度为 1
	for _, item := range items {
		// 因为意图识别模型下线 目前默认为知识查询
		// TODO wangran zpc
		resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = "知识查询"
	}
	return resMap, nil
}

func (s *SearchIntentionLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res macro.IntentionType) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.SearchIntentionLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetItemMeta().IntentionType = res
	return nil
}
