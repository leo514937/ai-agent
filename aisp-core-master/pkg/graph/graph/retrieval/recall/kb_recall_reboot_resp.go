package recall

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"

	//"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 召回结果重投
// @logicOutput: 0 | Merge结果。[]*data_frame.ItemData[entities.Item]

type KbRecallRebootRespLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewKbRecallRebootRespLogic(name string, config map[string]string) *KbRecallRebootRespLogic {
	res := &KbRecallRebootRespLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.realMerge
	return res
}

func (i *KbRecallRebootRespLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	respItems := make([]*data_frame.ItemData[entities.Item], 0)
	span, ctx, _, _ := logic_context.InitLogicContext(ctx, requestCtx, i.GetName(), "recall.KbRecallRebootRespLogic.realMerge")
	defer logic_context.DeferContext(span, i.GetName(), requestCtx, &respItems)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	// 召回结果
	recallItems, isOk := requestCtx.GetCommonContext().GetLogicData(conf.RecallCardLogicStoreKey.String()).([]*data_frame.ItemData[entities.Item])
	if isOk && recallItems != nil && len(recallItems) > 0 {
		return recallItems, nil
	}
	return respItems, nil
}
