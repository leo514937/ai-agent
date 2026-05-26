package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

type fetcherRes struct {
	embeddings    []float32
	embeddingType string
}

// @logicOutput: 0 | query embedding
type KlaraEmbeddingFetcherLogic struct {
	*logic.FetcherLogicDecorator[entities.RequestContext, entities.User, entities.Item, *fetcherRes]
	embeddingType  string
	embeddingModel string
}

func NewKlaraEmbeddingFetcherLogic(name string, config map[string]string) *KlaraEmbeddingFetcherLogic {
	res := &KlaraEmbeddingFetcherLogic{
		FetcherLogicDecorator: logic.NewFetcherLogicDecorator[entities.RequestContext, entities.User, entities.Item, *fetcherRes](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.embeddingType = config[conf.EmbeddingType]
	res.embeddingModel = config[conf.EmbeddingModelName]
	if res.embeddingType == "" {
		res.embeddingType = conf.EmbeddingTypeByBge
	}
	if res.embeddingModel == "" {
		res.embeddingModel = "ensemble"
	}

	return res
}

func (k *KlaraEmbeddingFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*fetcherRes, error) {

	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.KlaraEmbeddingFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]*fetcherRes)

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", k.GetName())
		return resMap, nil
	}

	bgeEmbeddingClient := impl.GetBgeEmbeddingClient(k.embeddingModel)
	var queries []string
	for _, item := range items {
		queries = append(queries, item.GetBizItem().Text)
	}

	var embeddings [][]float32
	switch k.embeddingType {
	case conf.EmbeddingTypeByBgeM3:
		embeddings = bgeEmbeddingClient.BatchInferBgeM3DenseEmb(ctx, queries)
	default:
		embeddings = bgeEmbeddingClient.BatchInferEmbedding(ctx, queries)
	}

	if len(embeddings) == len(items) {
		for i := 0; i < len(items); i++ {
			resMap[*data_frame.NewUniqueId(items[i].GetCommonItem().Id())] = &fetcherRes{embeddings: embeddings[i], embeddingType: k.embeddingType}
			requestCtx.DataMap().SetObjMap(logCtx, k.GetOutputName(0), embeddings[i])
		}
	}

	return resMap, nil
}

func (k *KlaraEmbeddingFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *fetcherRes) error {
	if res == nil {
		return nil
	}

	switch res.embeddingType {
	case conf.EmbeddingTypeByBgeM3:
		item.GetBizItem().GetItemMeta().BgeM3Embedding = res.embeddings
	default:
		item.GetBizItem().GetItemMeta().KlaraEmbedding = res.embeddings
	}
	return nil
}
