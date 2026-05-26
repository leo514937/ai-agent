package judge

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

var zhidaProStatsByBizFmt = macro.CommonStatsPrefix + ".%s.%s.%s"

// @logicAuthor: zhoupengcheng
// @logicInfo: 专业版文档路由
// @logicOutput: 0 | 路由结果 DocRouter
type DocRouterJudgeLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewDocRouterJudgeLogic(name string, config map[string]string) *DocRouterJudgeLogic {
	res := &DocRouterJudgeLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.realMapping
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (i *DocRouterJudgeLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemList []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "router.DocRouterJudgeLogic.realMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(itemList))

	startTime := time.Now().UnixMilli()
	// 根据当前业务来看 暂时不需要 doc router 模型
	route := entities.KnowledgeBase
	if len(requestCtx.GetBizContext().GetAssignmentDocKnowledgeBase()) > 0 || len(requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()) > 0 {
		route = entities.KnowledgeBase
		// 后续再根据业务情况 扩充 知识库 + 文档route逻辑
	} else {
		route = entities.SpecifiedDocAny
	}

	i.setSourceTypeAndState(ctx, requestCtx)
	requestCtx.GetBizContext().SetDocRouter(route)
	requestCtx.DataMap().SetString(logCtx, i.GetOutputName(0), route.String())

	i.saveTracing(util.GetJSONIgnoreError(map[string]any{
		"AssignmentPersonalKnowledgeBase": requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase(),
		"AssignmentDocKnowledgeBase":      requestCtx.GetBizContext().GetAssignmentDocKnowledgeBase(),
		"AssignmentDocs":                  requestCtx.GetBizContext().GetAssignmentDocs(),
	}), route.String(), startTime, requestCtx)
	return itemList, nil
}

func (i *DocRouterJudgeLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	route := entities.KnowledgeBase
	if routeByDataMap, routeExist := param.RequestContext.DataMap().GetString(ctx, i.GetOutputName(0)); routeExist && routeByDataMap != "" {
		route = entities.DocRouter(routeByDataMap)
	}
	return route.String()
}

func (i *DocRouterJudgeLogic) setSourceTypeAndState(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	var zhiDaProSourceType enums.ZhiDaProSourceType
	securityZhiDaProSourceType := "other"
	if len(requestCtx.GetBizContext().GetAssignmentDocKnowledgeBase()) > 0 && len(requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()) > 0 {
		zhiDaProSourceType = enums.ZhiDaProSourceByUserPublicAndPersonal
	} else {
		if len(requestCtx.GetBizContext().GetAssignmentDocKnowledgeBase()) > 0 {
			zhiDaProSourceType = enums.ZhiDaProSourceByPublic
			if len(requestCtx.GetBizContext().GetAssignmentDocKnowledgeBase()) == 1 {
				securityZhiDaProSourceType = requestCtx.GetBizContext().GetAssignmentDocKnowledgeBase()[0].String()
			}
		} else if len(requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()) > 0 {
			zhiDaProSourceType = enums.ZhiDaProSourceByPersonal
			if len(requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()) == 1 {
				securityZhiDaProSourceType = requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()[0].GetKnowledgeBaseType().String()
			}
		} else if len(requestCtx.GetBizContext().GetAssignmentDocs()) > 0 {
			zhiDaProSourceType = enums.ZhiDaProSourceByUserSpecifiedDoc
		}
	}
	requestCtx.GetBizContext().SetZhiDaProSourceType(zhiDaProSourceType)
	requestCtx.GetBizContext().SetSecurityZhiDaProSourceType(securityZhiDaProSourceType)
	// 记录请求数
	util.Increment(ctx, zhidaProStatsByBizFmt, "source_type", zhiDaProSourceType.String(), "count")
}

func (i *DocRouterJudgeLogic) saveTracing(input string, response string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   i.GetName(),
		LogicInput:  []string{input},
		LogicOutput: []string{response},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(i.GetName(), logicTracing)
}
