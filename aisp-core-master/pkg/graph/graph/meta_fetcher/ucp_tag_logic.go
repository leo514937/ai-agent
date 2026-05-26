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

type UcpTagLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, []*common.TagInfo]
	ucpRpc rpc.UcpGRPC
}

func NewUcpLogic(name string, config map[string]string) *UcpTagLogic {
	res := &UcpTagLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, []*common.TagInfo](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.ucpRpc = impl.DefaultUcpGrpcImpl
	return res
}

func (u *UcpTagLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User],
	items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]*common.TagInfo, error) {

	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.UcpTagLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId][]*common.TagInfo)

	var queries []string
	for _, item := range items {
		queries = append(queries, item.GetBizItem().Text)
	}

	tagInfos := u.ucpRpc.BatchGetBayesTagInfos(ctx, queries)
	if len(tagInfos) != len(items) {
		return resMap, nil
	}

	for i := 0; i < len(items); i++ {
		resMap[*data_frame.NewUniqueId(items[i].GetCommonItem().Id())] = tagInfos[i]
	}

	return resMap, nil
}

func (u *UcpTagLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res []*common.TagInfo) error {
	item.GetBizItem().GetItemMeta().BayesTagInfo = res
	return nil
}
