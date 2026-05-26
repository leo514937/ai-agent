package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 从 doc 中召回 chunk。不是召回算子，而是 meta fetcher算子，将召回的 chunks 存入 doc 的 meta 信息中

var specifiedDocCacheStatsPrefix = macro.CommonStatsPrefix + ".specified_chunk_emb.%s.count"

type ChunkRecallFetchLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, []*model.ItemMeta]
	redisDao dao.ChunkEmbeddingDao
}

func NewChunkRecallFetchLogic(name string, config map[string]string) *ChunkRecallFetchLogic {
	res := &ChunkRecallFetchLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, []*model.ItemMeta](name, config),
		redisDao:     impl.DefaultChunkEmbeddingDaoImpl,
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	return res
}

func (s *ChunkRecallFetchLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]*model.ItemMeta, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.DocumentParsingFetchLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId][]*model.ItemMeta)

	// 构建内存索引，召回 topk 的 chunk
	// 读取 tidb，查到 chunk 对应的 text、page、box
	afterFilterDocs := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().GetItemMeta().HashChunkEmbedding
	})
	util.TimingInMilSec(ctx, specifiedDocCacheStatsPrefix, float64(len(afterFilterDocs)), "exist")
	util.TimingInMilSec(ctx, specifiedDocCacheStatsPrefix, float64(len(items)-len(afterFilterDocs)), "not_exist")

	return resMap, nil
}

func (s *ChunkRecallFetchLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res []*model.ItemMeta) error {
	item.GetBizItem().GetItemMeta().Chunks = res
	return nil
}
