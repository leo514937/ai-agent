package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: wangran
// @logicInfo: doc meta 信息中的 chunk rerank、chunk 合并。最终结果存入 doc 的 meta 信息中

type ChunkRerankFetchLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, []*model.ItemMeta]
	redisDao dao.ChunkEmbeddingDao
}

func NewChunkRerankFetchLogic(name string, config map[string]string) *ChunkRerankFetchLogic {
	res := &ChunkRerankFetchLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, []*model.ItemMeta](name, config),
		redisDao:     impl.DefaultChunkEmbeddingDaoImpl,
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	return res
}

func (s *ChunkRerankFetchLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]*model.ItemMeta, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.DocumentParsingFetchLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId][]*model.ItemMeta)

	// 获取 chunk rerank 分数，chunk 合并

	return resMap, nil
}

func (s *ChunkRerankFetchLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res []*model.ItemMeta) error {
	item.GetBizItem().GetItemMeta().Chunks = res
	return nil
}
