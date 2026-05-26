package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: wangran
// @logicInfo: doc topk 的 chunk 送给大模型总结

type DocSummaryFetchLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, string]
	redisDao dao.ChunkEmbeddingDao
}

func NewDocSummaryFetchLogic(name string, config map[string]string) *DocSummaryFetchLogic {
	res := &DocSummaryFetchLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, string](name, config),
		redisDao:     impl.DefaultChunkEmbeddingDaoImpl,
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	return res
}

func (s *DocSummaryFetchLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]string, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.ChunkExistFetchLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]string)

	// 对于每篇 doc，使用其 chunks，送给大模型总结
	// 1、chunk 选取个数
	// 2、prompt 拼接
	// 3、调用大模型chat，无需安全
	// 4、apollo 配置可选关闭。关闭时没有 summary，后续「归并映射」将会降级成 rerank top1 的 chunk

	return resMap, nil
}

func (s *DocSummaryFetchLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res string) error {
	item.GetBizItem().GetItemMeta().Summary = res
	return nil
}
