package security_post

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
)

// RecallAndSafetyJudgeChoose 安全审核结果判断
// @logicAuthor: zhoupengcheng
// @logicInfo: 安全审核结果判断（Recall版）
// @logicInput: 0 | 安全审核结果判断（Query版）.bool
// @logicInput: 1 | 安全审核结果判断（QueryMerge版）.bool
// @logicInput: 2 | query faq的回答 .string
// @logicInput: 3 | queryMerge faq的回答 .string
type RecallAndSafetyJudgeChoose struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewRecallAndSafetyJudgeChoose(name string, config map[string]string) *RecallAndSafetyJudgeChoose {
	res := &RecallAndSafetyJudgeChoose{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.buildResponse
	res.NeedSignal = true
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}
func (q *RecallAndSafetyJudgeChoose) buildResponse(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "recall_security_post.QuerySecurityJudgeLogic.buildResponse")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "security_post.RecallAndSafetyJudgeChoose.buildResponse",
	})
	logger.Debug(ctx, "do running...")
	resp := make([]*data_frame.ItemData[entities.Item], 0)
	// 拍平 ItemLists
	items := lo.Flatten(itemLists)

	securityPassed, faqAnswerPresent, showRecallIfFaqAnswerPresent := q.isSecurityAllPassedByStage(logCtx, requestCtx)
	if securityPassed {
		// 召回内容 items
		recallItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
			return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
		})
		resp = recallItems
	} else if faqAnswerPresent && showRecallIfFaqAnswerPresent {
		// 命中faq，且需要展示召回的情况
		// 召回内容 items
		recallItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
			return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
		})
		answerItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
			return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeLLMAnswer &&
				item.GetBizItem().GetSecurity().IsSecurityAllPassed()
		})

		resp = append(recallItems, recallItems...)
		if len(answerItems) > 0 {
			item := util2.RandomElement(answerItems)
			resp = append(resp, item)
		}
	} else {
		// 安全未通过 获取兜底已通过的answer
		defItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
			return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeLLMAnswer &&
				item.GetBizItem().GetSecurity().IsSecurityAllPassed()
		})
		if len(defItems) > 0 {
			item := util2.RandomElement(defItems)
			resp = append(resp, item)
		}
	}

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(itemLists))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(resp))
	return resp, nil
}

func (q *RecallAndSafetyJudgeChoose) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	securityPassed, faqAnswerPresent, showRecallIfFaqAnswerPresent := q.isSecurityAllPassedByStage(ctx, param.RequestContext)
	if securityPassed {
		macro.ProcessNodeLog.Infof(ctx, "RecallAndSafetyJudgeChoose chooseKey Normal")
		return entities.Normal
	} else if faqAnswerPresent && showRecallIfFaqAnswerPresent {
		macro.ProcessNodeLog.Infof(ctx, "RecallAndSafetyJudgeChoose chooseKey UploadRecallThenBreak.")
		return entities.UploadRecallThenBreak
	} else {
		macro.ProcessNodeLog.Infof(ctx, "RecallAndSafetyJudgeChoose chooseKey Break.")
		return entities.Break
	}
}

// isSecurityAllPassedByStage 用于内部判断 query 和 query merge 安全审核已经通过
func (q *RecallAndSafetyJudgeChoose) isSecurityAllPassedByStage(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) (bool, bool, bool) {
	querySecurityAllPassed, querySecurityAllPassedOk := requestCtx.DataMap().GetBool(ctx, q.GetInputName(0))
	queryMergeSecurityAllPassed, queryMergeSecurityAllPassedOk := requestCtx.DataMap().GetBool(ctx, q.GetInputName(1))
	faqAnswer, _ := requestCtx.DataMap().GetString(ctx, q.GetInputName(2))
	queryMergeFaqAnswer, _ := requestCtx.DataMap().GetString(ctx, q.GetInputName(3))
	showRecallIfFaqAnswerPresent, _ := requestCtx.DataMap().GetBool(ctx, q.GetInputName(4))
	showRecallIfQueryMergeFaqAnswerPresent, _ := requestCtx.DataMap().GetBool(ctx, q.GetInputName(5))

	passedRes := false
	if querySecurityAllPassedOk && queryMergeSecurityAllPassedOk {
		passedRes = querySecurityAllPassed && queryMergeSecurityAllPassed
	} else if querySecurityAllPassedOk && !queryMergeSecurityAllPassedOk {
		passedRes = querySecurityAllPassed
	}
	return passedRes, faqAnswer != "" || queryMergeFaqAnswer != "", showRecallIfFaqAnswerPresent || showRecallIfQueryMergeFaqAnswerPresent
}
