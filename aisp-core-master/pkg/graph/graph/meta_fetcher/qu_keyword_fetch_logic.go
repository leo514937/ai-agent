package meta_fetcher

import (
	"context"
	"sort"

	query_profile "git.in.zhihu.com/pb-go/search-proto/query-profile"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

type QuKeywordFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, []*query_profile.QpTerm]
	qpGrpc rpc.QueryProfileRpc
}

func NewQuKeywordFetcherLogic(name string, config map[string]string) *QuKeywordFetcherLogic {
	res := &QuKeywordFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, []*query_profile.QpTerm](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.qpGrpc = impl.DefaultQpImpl
	return res
}

func (q *QuKeywordFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]*query_profile.QpTerm, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.QuKeywordFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId][]*query_profile.QpTerm)

	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", q.GetName())
		return resMap, nil
	}

	// itemMerge 的结果，items长度为1
	for _, item := range items {
		queryTerms := q.qpGrpc.GetQueryKeyWords(ctx, item.GetBizItem().Text)

		// 按 importance 倒序
		sort.Slice(queryTerms, func(i, j int) bool {
			return queryTerms[i].GetTermImportance() > queryTerms[j].GetTermImportance()
		})

		resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = queryTerms
	}

	return resMap, nil
}

func (q *QuKeywordFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res []*query_profile.QpTerm) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.QuKeywordFetcherLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetItemMeta().QuKeywords = res
	return nil
}
