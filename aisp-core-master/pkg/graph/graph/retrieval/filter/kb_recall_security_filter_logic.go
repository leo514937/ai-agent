package filter

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: wangran
// @logicInfo: 内容安全过滤。
// 与 security post 的区别是：
// 1、仅过滤逻辑，不会将安全通过与否的状态记录到整个 requestContext 里，不会影响对话历史等逻辑
// 2、不输出条件边
type KbRecallSecurityFilterLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewKbRecallSecurityFilterLogic(name string, config map[string]string) *KbRecallSecurityFilterLogic {
	res := &KbRecallSecurityFilterLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.NeedFilterItemsFunc = res.needFilterItems
	return res
}

func (c *KbRecallSecurityFilterLogic) needFilterItems(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User],
	items []*data_frame.ItemData[entities.Item]) (map[*data_frame.ItemData[entities.Item]]string, error) {

	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "filter.ContentRegulateFilterLogic.needFilterItems")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[*data_frame.ItemData[entities.Item]]string)

	if len(items) == 0 {
		constant.DataInputNodeLog.Infof(logCtx, "empty items")
		return resMap, nil
	}

	// 用于记录 tracing
	hasSecurityPassedItem := false
	var oneSecurityResult *model.Security

	for _, item := range items {
		if !item.GetBizItem().GetSecurity().IsSecurityAllPassed() {
			resMap[item] = "security_review_failed"
		} else {
			hasSecurityPassedItem = true
			oneSecurityResult = item.GetBizItem().GetSecurity()
		}
	}

	if !hasSecurityPassedItem {
		oneSecurityResult = items[0].GetBizItem().GetSecurity()
	}

	c.saveSecurityTracing(logCtx, hasSecurityPassedItem, oneSecurityResult, requestCtx)

	return resMap, nil
}

func (c *KbRecallSecurityFilterLogic) saveSecurityTracing(logCtx context.Context, hasSecurityPassedItem bool, security *model.Security,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {

	securityTracing := &proto.SecurityTracing{
		Stage:            proto.BusinessStage_RETRIEVAL,
		IsPass:           hasSecurityPassedItem,
		FailReason:       security.ReviewResult.GetFailReason(),
		DoSecurityReview: security.ReviewResult != nil,
	}
	securityChan := requestCtx.GetBizContext().ProcessTracing().SecurityTracing
	if len(securityChan) < entities.MaxTracingChanSize {
		securityChan <- securityTracing
	}

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(securityTracing))
	constant.DataOutputNodeLog.Infof(logCtx, "is security passed:%v", hasSecurityPassedItem)
}
