package retrieval

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: DeepSearch 后处理

type KbDeepSearchAfterHandlerLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewKbDeepSearchAfterHandlerLogic(name string, config map[string]string) *KbDeepSearchAfterHandlerLogic {
	res := &KbDeepSearchAfterHandlerLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.realMerge
	return res
}

func (q *KbDeepSearchAfterHandlerLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "retrieval.KbDeepSearchAfterHandlerLogic.realMerge")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	cards := make([]*proto.ChatCard, 0)
	items := lo.Flatten(itemLists)
	// 后处理(当被Research 最终选中的召回内容就是全部被选中的)
	for _, item := range items {
		if item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk {
			item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used = true
			cards = append(cards, item.GetBizItem().ToChatCardByZhiDa())
		}
	}

	// 发送 agent 最终 refs
	requestCtx.GetBizContext().GetChatEvent().GetReferenceProducer().Send(cards).Done()

	return items, nil
}
