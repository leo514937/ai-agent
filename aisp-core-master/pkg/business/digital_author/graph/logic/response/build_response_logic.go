package response

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	digitalModel "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type DigitalAuthorBuildResponseLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewDigitalAuthorBuildResponseLogic(name string, config map[string]string) *DigitalAuthorBuildResponseLogic {
	res := &DigitalAuthorBuildResponseLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.buildResponse
	res.NeedSignal = true
	return res
}

func (b *DigitalAuthorBuildResponseLogic) buildResponse(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "response.DigitalAuthorBuildResponseLogic.buildResponse")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	// 先做合并
	var itemList []*data_frame.ItemData[entities.Item]
	for _, i := range itemLists {
		itemList = append(itemList, i...)
	}

	for _, item := range itemList {
		if item.GetBizItem().ChatRespType == proto.ChatRespType_UNKNOWN_RESP {
			continue
		}
		// 出任务的 summary 单独存放
		if item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeSummary {
			requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).SetMultiChatSummary(item.GetBizItem().Text)
		} else {
			requestCtx.GetBizContext().AppendResponseItem(item.GetBizItem())
		}
	}
	return itemList, nil
}
