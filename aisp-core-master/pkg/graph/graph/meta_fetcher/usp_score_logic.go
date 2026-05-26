package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type UspScoreLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]float64]
	similarRpc rpc.SimilarGRPC
}

func NewUspScoreLogic(name string, config map[string]string) *UspScoreLogic {
	res := &UspScoreLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]float64](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.similarRpc = impl.DefaultSimilarGrpcImpl
	return res
}

func (u *UspScoreLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User],
	items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]map[string]float64, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.UspScoreLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]map[string]float64)

	var queries []string
	for _, item := range items {
		queries = append(queries, item.GetBizItem().Text)
	}

	// 与用户贝叶斯领域分类计算相似度
	bayes := requestCtx.GetBizContext().AuthorInfo().UserMeta().GetBayesNames()
	var similarScore []float64
	resp, err := u.similarRpc.GetSimilarV2(ctx, queries, bayes, rpc.SimilarSourceCodeV2Code)
	if err == nil && resp != nil {
		for _, item := range resp.GetItems() {
			similarScore = append(similarScore, item.GetScore())
		}
	}
	if len(similarScore) == 0 || len(similarScore) != len(items)*len(bayes) {
		return resMap, nil
	}

	for i := 0; i < len(similarScore); i++ {
		itemUniqueKey := *data_frame.NewUniqueId(items[i/len(bayes)].GetCommonItem().Id())
		if _, exist := resMap[itemUniqueKey]; !exist {
			resMap[itemUniqueKey] = map[string]float64{}
		}
		resMap[itemUniqueKey][bayes[i%len(bayes)]] = similarScore[i]
	}

	return resMap, nil
}

func (u *UspScoreLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res map[string]float64) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.UspScoreLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetItemMeta().RequestThemeSimilar = res
	return nil
}
