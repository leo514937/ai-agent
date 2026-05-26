package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: wangran
// @logicInfo: doc 获取 chunk、chunk rerank、chunk 合并。最终结果存入 doc 的 meta 信息中

type ChunkRecallAndRerankFetchLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, []*model.ItemMeta]
}

func NewChunkRecallAndRerankFetchLogic(name string, config map[string]string) *ChunkRecallAndRerankFetchLogic {
	res := &ChunkRecallAndRerankFetchLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, []*model.ItemMeta](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	return res
}

func (s *ChunkRecallAndRerankFetchLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]*model.ItemMeta, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.ChunkExistFetchLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId][]*model.ItemMeta)

	// 把 KbRecallChunkAndScoreLogic 改造成 meta fetcher 算子，放在这里

	return resMap, nil
}

func (s *ChunkRecallAndRerankFetchLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res []*model.ItemMeta) error {
	item.GetBizItem().GetItemMeta().Chunks = res
	return nil
}
