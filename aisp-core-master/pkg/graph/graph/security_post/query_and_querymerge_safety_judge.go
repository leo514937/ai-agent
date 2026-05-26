package security_post

import (
	"context"

	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 安全审核结果判断（QueryAndQueryMerge）
// @logicInput: 0 | 安全审核结果判断（Query版）.bool
// @logicInput: 1 | 安全审核结果判断（QueryMerge版）.bool
type QueryAndQueryMergeSafetyJudge struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewQueryAndQueryMergeSafetyJudge(name string, config map[string]string) *QueryAndQueryMergeSafetyJudge {
	res := &QueryAndQueryMergeSafetyJudge{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.buildResponse
	res.NeedSignal = true
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}
func (q *QueryAndQueryMergeSafetyJudge) buildResponse(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security_post.QueryAndQueryMergeSafetyJudge.buildResponse")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "security_post.QueryAndQueryMergeSafetyJudge.buildResponse",
	})
	logger.Debug(ctx, "do running...")
	resp := make([]*data_frame.ItemData[entities.Item], 0)
	// 拍平 ItemLists
	items := lo.Flatten(itemLists)

	if !q.isSecurityAllPassedByStage(ctx, logCtx, requestCtx) {
		// 安全未通过 获取兜底已通过的answer
		defItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
			return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeLLMAnswer &&
				item.GetBizItem().GetSecurity().IsSecurityAllPassed()
		})
		if len(defItems) > 0 {
			item := util2.RandomElement(defItems)
			resp = append(resp, item)
		}
	} else {
		// 安全通过 放行以上内容
		resp = append(resp, items...)
	}

	constant.DataInputNodeLog.Infof(ctx, "%s", util.GetJSONIgnoreError(itemLists))
	constant.DataOutputNodeLog.Infof(ctx, "%s", util.GetJSONIgnoreError(resp))
	return resp, nil
}
func (q *QueryAndQueryMergeSafetyJudge) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security_post.QuerySecurityJudgeLogic.chooseKey")
	defer span.Finish()
	span.LogFields(log.Message("RouterAndSafetyJudgeChoose chooseKey start."),
		log.Json("bizContext", param.RequestContext.GetBizContext()),
	)

	if q.isSecurityAllPassedByStage(ctx, logCtx, param.RequestContext) {
		span.LogFields(log.Message("RouterAndSafetyJudgeChoose chooseKey Normal."))
		return entities.Normal
	} else {
		span.LogFields(log.Message("RouterAndSafetyJudgeChoose chooseKey Break."))
		return entities.Break
	}
}

// isSecurityAllPassedByStage 用于内部判断 query 和 query merge 安全审核已经通过
func (q *QueryAndQueryMergeSafetyJudge) isSecurityAllPassedByStage(ctx context.Context, logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
	querySecurityAllPassed, querySecurityAllPassedOk := requestCtx.DataMap().GetBool(logCtx, q.GetInputName(0))
	queryMergeSecurityAllPassed, queryMergeSecurityAllPassedOk := requestCtx.DataMap().GetBool(logCtx, q.GetInputName(1))
	passedRes := false
	if querySecurityAllPassedOk && queryMergeSecurityAllPassedOk {
		passedRes = querySecurityAllPassed && queryMergeSecurityAllPassed
	} else if querySecurityAllPassedOk && !queryMergeSecurityAllPassedOk {
		passedRes = querySecurityAllPassed
	}
	return passedRes
}
