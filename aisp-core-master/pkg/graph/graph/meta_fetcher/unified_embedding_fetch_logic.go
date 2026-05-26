package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/common"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type UnifiedEmbeddingFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, []float32]
	unifiedEmbGrpc rpc.UnifiedEmbGRPC
}

func NewUnifiedEmbeddingFetcherLogic(name string, config map[string]string) *UnifiedEmbeddingFetcherLogic {
	res := &UnifiedEmbeddingFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, []float32](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.unifiedEmbGrpc = impl.DefaultUnifiedEmbGrpcImpl
	return res
}

func (u *UnifiedEmbeddingFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]float32, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.UnifiedEmbeddingFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId][]float32)

	// itemMerge 的结果，items长度为1
	for _, item := range items {
		embedding := u.unifiedEmbGrpc.GetEmbedding(ctx, item.GetBizItem().Text, common.EmbeddingType_TextQueryMoco64d)
		resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = embedding
	}

	return resMap, nil
}

func (u *UnifiedEmbeddingFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res []float32) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.UnifiedEmbeddingFetcherLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetItemMeta().UnifiedEmbedding = res
	return nil
}
