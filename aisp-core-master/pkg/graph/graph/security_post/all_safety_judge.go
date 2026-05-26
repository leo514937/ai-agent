package security_post

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// QuerySecurityJudgeLogic
// @logicAuthor: wangran
// @logicInfo: 安全审核结果判断
// @logicOutput: 0 | 是否通过了所有安全相关的校验。bool
type QuerySecurityJudgeLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	stage proto.BusinessStage
}

func NewQuerySecurityJudgeLogic(name string, config map[string]string) *QuerySecurityJudgeLogic {
	res := &QuerySecurityJudgeLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.buildResponse
	res.NeedSignal = true
	res.SetChooseKeyFunc(res.chooseKey)
	res.stage = proto.BusinessStage(cast.ToInt32(config[conf.SecurityBusinessStage.ToConvert()]))
	return res
}

func (q *QuerySecurityJudgeLogic) buildResponse(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security_post.QuerySecurityJudgeLogic.buildResponse")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	var itemList = lo.Flatten(itemLists)

	queryItems := q.getQueryItems(itemList)
	answerItems := q.getAnswerItems(itemList)

	var hasSecurityPassedItem bool
	var itemUnPassSecurity *model.Security
	var answerDialog *model.DialogRecord
	resp := make([]*data_frame.ItemData[entities.Item], 0)

	// 是否不允许校正安审结果
	isNotAllowReviseSecurityResult := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.IsNotAllowReviseSecurityResult.ToConvert()))

	if len(answerItems) > 0 {
		// 1. Answer 合并安全处理结果，并返回是否安全通过标识
		hasSecurityPassedItem, itemUnPassSecurity = q.mergeSecurityResAndReturnFlag(ctx, requestCtx, answerItems)
		if hasSecurityPassedItem && itemUnPassSecurity.IsSecurityAllPassed() {
			resp = q.getPassedItem(ctx, itemList)
			answerDialog = q.getAnswerDialog(requestCtx, resp)
		} else {
			resItems := q.genUnPassedAnswerItem(ctx, requestCtx, answerItems, isNotAllowReviseSecurityResult)
			resp = append(resp, resItems...)
			answerDialog = updateDialogCache(hasSecurityPassedItem, requestCtx, resp)
		}
	} else if len(queryItems) > 0 {
		// 2. Query 或 QueryMerge 合并安全处理结果，并返回是否安全通过标识
		hasSecurityPassedItem, itemUnPassSecurity = q.mergeSecurityResAndReturnFlag(ctx, requestCtx, queryItems)
		if hasSecurityPassedItem && itemUnPassSecurity.IsSecurityAllPassed() {
			resp = q.getPassedItem(ctx, itemList)
			answerDialog = q.getAnswerDialog(requestCtx, resp)
		} else {
			resItems := q.genUnPassedAnswerItem(ctx, requestCtx, queryItems, isNotAllowReviseSecurityResult)
			resp = append(resp, resItems...)
			answerDialog = updateDialogCache(hasSecurityPassedItem, requestCtx, resp)
		}
	} else {
		// 3. 其他 合并安全处理结果，并返回是否安全通过标识
		hasSecurityPassedItem, itemUnPassSecurity = q.mergeSecurityResAndReturnFlag(ctx, requestCtx, itemList)
		if hasSecurityPassedItem {
			resp = q.getPassedItem(ctx, itemList)
		}
	}

	// 保存 answer 结果到上下文
	if answerDialog != nil {
		requestCtx.GetBizContext().SetCurrentDialogueByAnswer(answerDialog)
	}

	requestCtx.DataMap().SetBool(logCtx, q.GetOutputName(0), hasSecurityPassedItem)
	q.saveSecurityTracing(logCtx, hasSecurityPassedItem, itemUnPassSecurity, requestCtx)
	return resp, nil
}

func (q *QuerySecurityJudgeLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security_post.QuerySecurityJudgeLogic.chooseKey")
	defer span.Finish()

	span.LogFields(log.Message("QuerySecurityJudgeLogic chooseKey start."),
		log.Json("bizContext", param.RequestContext.GetBizContext()),
	)

	isSecurityAllPassed, _ := param.RequestContext.DataMap().GetBool(logCtx, q.GetOutputName(0))
	if isSecurityAllPassed {
		span.LogFields(log.Message("QuerySecurityJudgeLogic chooseKey Normal. "))
		return entities.Normal
	} else {
		span.LogFields(log.Message("QuerySecurityJudgeLogic chooseKey Break."))
		return entities.Break
	}
}

// 组装 answer dialog
func (q *QuerySecurityJudgeLogic) getAnswerDialog(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], itemList []*data_frame.ItemData[entities.Item]) *model.DialogRecord {
	for _, item := range q.getAnswerItems(itemList) {
		// 创建answer dialog
		answerDialog := entities.NewAnswerDialogFormProtoChatRequest(
			requestCtx.GetBizContext(), item.GetBizItem().Text, model.DialogCreateTypeLLM, model.DialogErrorTypeNormal)
		return answerDialog
	}
	return nil
}

// 整体安审通过，去除未通过的item
func (q *QuerySecurityJudgeLogic) getPassedItem(ctx context.Context, itemList []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	log.Infof(ctx, "QuerySecurityJudgeLogic getPassedItem len(itemList): %d", len(itemList))

	var result []*data_frame.ItemData[entities.Item]
	for _, item := range itemList {
		if item.GetBizItem().GetSecurity().IsSecurityAllPassed() {
			result = append(result, item)
		}
	}
	return result
}

// 获取所有的answer item
func (q *QuerySecurityJudgeLogic) getAnswerItems(itemList []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	return lo.Filter(itemList, func(item *data_frame.ItemData[entities.Item], _ int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeLLMAnswer
	})
}

// 获取所有的query item
func (q *QuerySecurityJudgeLogic) getQueryItems(itemList []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	return lo.Filter(itemList, func(item *data_frame.ItemData[entities.Item], _ int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeQuery || item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeQueryMerge
	})
}

// 安审未通过，拼接安审结果，跳转 response 模块
func (q *QuerySecurityJudgeLogic) genUnPassedAnswerItem(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	itemList []*data_frame.ItemData[entities.Item], isNotAllowReviseSecurityResult bool) []*data_frame.ItemData[entities.Item] {

	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "security_post.QuerySecurityJudgeLogic.genUnPassedItem",
		"stage": q.stage.String(),
	})

	logger.Infof(ctx, "len(itemList): %d", len(itemList))

	// 只获取answer item
	unPassedItems := lo.Filter(itemList, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return !item.GetBizItem().GetSecurity().IsSecurityAllPassed()
	})

	if len(unPassedItems) == 0 {
		return []*data_frame.ItemData[entities.Item]{}
	}

	bizItem := unPassedItems[0].GetBizItem()

	var chatRespType proto.ChatRespType
	message := ""
	if bizItem.GetSecurity().RedLine != "" {
		chatRespType = proto.ChatRespType_RED_LINE
		message = bizItem.GetSecurity().RedLine
	} else if bizItem.GetSecurity().FAQ != "" {
		chatRespType = proto.ChatRespType_FAQ
		message = bizItem.GetSecurity().FAQ
	} else {
		chatRespType = proto.ChatRespType_REFUSE
		message = config.GetString("stream_chat.sec_message", graph_constant.DefaultSecurityRefuseMessage)
	}

	// 最终返回的item 一定是是经过兜底的 所以是安全的
	respMessage := &proto.ChatMessage{
		MessageId:   requestCtx.GetBizContext().RespMessageId(),
		TimestampMs: time.Now().UnixMilli(),
		Type:        bizItem.Type,
		Text:        message,
	}
	item := entities.ItemFromMessageByAnswer(respMessage)
	item.ChatRespType = chatRespType
	// 不允许校正时 需要把原有的安审结果返回
	if isNotAllowReviseSecurityResult {
		item.Security = bizItem.GetSecurity()
	}
	resList := []*data_frame.ItemData[entities.Item]{
		item.IntoFrameItem(requestCtx),
	}
	return resList
}

// mergeSecurityResAndReturnFlag 合并多路安全审核内容到一个最终安全结果，并返回是否安全通过
func (q *QuerySecurityJudgeLogic) mergeSecurityResAndReturnFlag(
	ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	items []*data_frame.ItemData[entities.Item]) (bool, *model.Security) {
	hasSecurityPassedItem := false
	mergeUnPassedSecurity := &model.Security{}
	if len(items) == 0 {
		return false, mergeUnPassedSecurity
	}
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "security_post.QuerySecurityJudgeLogic.buildResponse",
		"stage": q.stage.String(),
	})
	// 遍历 items，如果存在安审通过的内容，则当前环节安审通过，链路正常进行
	for _, item := range items {
		bizItem := item.GetBizItem()
		logger.Infof(ctx, "for range itemList. bizItem: %s", util.GetJSONIgnoreError(bizItem))
		if bizItem.GetSecurity() == nil {
			continue
		}
		logger.Infof(ctx, "logic:%s item:%s security:%s", q.GetName(), bizItem.Text, util.GetJSONIgnoreError(bizItem.GetSecurity()))
		if bizItem.GetSecurity().ReviewResult == nil {
			// 新
			util.Increment(ctx, macro.CommonStatsPrefix+".security_review.empty.count")
			// 老
			statsd.Increment(fmt.Sprintf(macro.OriginCommonStatsPrefix+".security_review.empty.count", requestCtx.GetBizContext().Scenes()))
		}

		// 合并安全处理结果，同时对多个相同的安全处理合并为一个
		if !bizItem.GetSecurity().IsSecurityAllPassed() {
			// 合并多出安全元数据 用于记录tracing日志
			if bizItem.GetSecurity().RedLine != "" {
				mergeUnPassedSecurity.RedLine = bizItem.GetSecurity().RedLine
			}
			if bizItem.GetSecurity().FAQ != "" {
				mergeUnPassedSecurity.FAQ = bizItem.GetSecurity().FAQ
			}
			if len(bizItem.GetSecurity().KnowLedgeEnhance) > 0 {
				mergeUnPassedSecurity.KnowLedgeEnhance = append(mergeUnPassedSecurity.KnowLedgeEnhance, bizItem.GetSecurity().KnowLedgeEnhance...)
			}
			if bizItem.GetSecurity().ReviewResult != nil && !bizItem.GetSecurity().ReviewResult.IsAvailable {
				mergeUnPassedSecurity.ReviewResult = bizItem.GetSecurity().ReviewResult
			}
		} else {
			hasSecurityPassedItem = true
		}
	}
	return hasSecurityPassedItem, mergeUnPassedSecurity
}

func (q *QuerySecurityJudgeLogic) saveSecurityTracing(logCtx context.Context, hasSecurityPassedItem bool, security *model.Security, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	securityTracing := &proto.SecurityTracing{
		Stage:            q.stage,
		RedLine:          security.RedLine,
		Faq:              security.FAQ,
		IsPass:           security.ReviewResult.GetIsAvailable(),
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
