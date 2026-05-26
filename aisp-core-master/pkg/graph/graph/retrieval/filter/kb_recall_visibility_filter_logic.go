package filter

import (
	"context"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

const visibilityFilterReasonFmt = "visibility_filter_%s"

// @logicAuthor: wangran
// @logicInfo: 知识库可见性过滤。由于索引更新延迟，可能会出现召回的内容在知识库中已经由公开转成私密的情况，因此需要过滤掉这些内容。

type KbRecallVisibilityFilterLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewKbRecallVisibilityFilterLogic(name string, config map[string]string) *KbRecallVisibilityFilterLogic {
	res := &KbRecallVisibilityFilterLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.NeedFilterItemsFunc = res.needFilterItems
	return res
}

func (c *KbRecallVisibilityFilterLogic) needFilterItems(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[*data_frame.ItemData[entities.Item]]string, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "filter.KbRecallSiteLevelFilterLogic.needFilterItems")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[*data_frame.ItemData[entities.Item]]string)
	for _, item := range items {
		kbCreator := item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KnowledgeBaseCreator
		kbId := item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KnowledgeBaseId
		visibility := item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KnowledgeBaseVisibility

		if kbId != 0 && // 根据知识库召回
			kbCreator != 0 && kbCreator != requestCtx.GetBizContext().MemberId() && // 不是自己的知识库
			visibility == proto.KnowledgeBaseVisibility_PRIVATE { // 私密的
			resMap[item] = fmt.Sprintf(visibilityFilterReasonFmt, "private")
		}

	}

	return resMap, nil
}
