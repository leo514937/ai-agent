package meta_fetcher

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 获取知识库可见性信息

type KnowledgeBaseVisibilityMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, proto.KnowledgeBaseVisibility]
	aiIngressClient rpc.AiIngressRPC
}

func NewKnowledgeBaseVisibilityMetaFetcherLogic(name string, config map[string]string) *KnowledgeBaseVisibilityMetaFetcherLogic {
	res := &KnowledgeBaseVisibilityMetaFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, proto.KnowledgeBaseVisibility](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.aiIngressClient = impl.DefaultAiIngressRPCImpl
	return res
}

func (k *KnowledgeBaseVisibilityMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]proto.KnowledgeBaseVisibility, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.KnowledgeBaseVisibilityMetaFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]proto.KnowledgeBaseVisibility)

	// 针对其他人创建的知识库召回的内容，获取可见性
	otherUserCreatedKbItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], _ int) bool {
		recallSourceInfo := item.GetBizItem().GetItemMeta().GetRecallSourceInfo()
		return recallSourceInfo.KnowledgeBaseCreator != requestCtx.GetBizContext().MemberId() && recallSourceInfo.KnowledgeBaseId > 0
	})

	knowledgeBaseIds := lo.Map(otherUserCreatedKbItems, func(item *data_frame.ItemData[entities.Item], _ int) int64 {
		return item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KnowledgeBaseId
	})

	if len(knowledgeBaseIds) == 0 {
		return resMap, nil
	}

	kbVisibility := k.aiIngressClient.BatchGetKnowledgeBaseVisibility(ctx, knowledgeBaseIds)

	for _, item := range items {
		resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = kbVisibility[item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KnowledgeBaseId]
	}

	constant.DataOutputNodeLog.Infof(logCtx, "%v", util.GetJSONIgnoreError(kbVisibility))

	return resMap, nil
}

func (k *KnowledgeBaseVisibilityMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res proto.KnowledgeBaseVisibility) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.KnowledgeBaseVisibilityMetaFetcherLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KnowledgeBaseVisibility = res

	return nil
}
