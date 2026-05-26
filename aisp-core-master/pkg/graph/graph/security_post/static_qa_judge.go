package security_post

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

type StaticQAJudgeLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	stage proto.BusinessStage
}

// 只判断红线必答是否通过
func NewStaticQAJudgeLogic(name string, config map[string]string) *StaticQAJudgeLogic {
	res := &StaticQAJudgeLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.stage = proto.BusinessStage(cast.ToInt32(config[conf.SecurityBusinessStage.ToConvert()]))
	res.MergeFunc = res.buildResponse
	res.NeedSignal = true
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (q *StaticQAJudgeLogic) buildResponse(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.StaticQAJudgeLogic.buildResponse")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	var itemList = itemLists[0]
	unPassedSecurity := &model.Security{}
	logger := log.WithField(ctx, "StaticQAJudgeLogic", map[string]any{"Query": requestCtx.GetBizContext().GetCurrentDialogue().Query, "itemLists": itemLists})
	isSecurityPassed := true
	// 遍历 items，如果命中静态库，环节结束
	for _, item := range itemList {
		isRedLine := item.GetBizItem().GetSecurity().RedLine != ""
		isFAQ := item.GetBizItem().GetSecurity().FAQ != ""
		if isRedLine || isFAQ {
			isSecurityPassed = false
			unPassedSecurity = item.GetBizItem().GetSecurity()
			logger.Infof(ctx, "item:%s hit redLine or faq", item.GetBizItem().Text)
			break
		}
	}

	resItems := q.genItem(requestCtx, itemList)
	// 如果安全审核失败 则更新 对话记录
	if !isSecurityPassed {
		answerDialog := updateDialogCache(isSecurityPassed, requestCtx, resItems)
		requestCtx.GetBizContext().SetCurrentDialogueByAnswer(answerDialog)
	}

	q.saveSecurityTracing(logCtx, isSecurityPassed, unPassedSecurity, requestCtx)
	requestCtx.DataMap().SetBool(logCtx, q.GetOutputName(0), isSecurityPassed)
	return resItems, nil
}

func (q *StaticQAJudgeLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "security.StaticQAJudgeLogic.chooseKey")
	defer span.Finish()

	isSecurityAllPassed, _ := param.RequestContext.DataMap().GetBool(logCtx, q.GetOutputName(0))
	if isSecurityAllPassed {
		return entities.Normal
	} else {
		return entities.Break
	}
}

// 没有命中静态库的，返回原始 item；命中静态库的，按照 faq > 红线必答的顺序返回
func (q *StaticQAJudgeLogic) genItem(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	itemList []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	if len(itemList) == 0 {
		return []*data_frame.ItemData[entities.Item]{}
	}

	var staticAnswer *data_frame.ItemData[entities.Item]
	for _, item := range itemList {
		if item.GetBizItem().GetSecurity().FAQ != "" || item.GetBizItem().GetSecurity().RedLine != "" {
			staticAnswer = item
			break
		}
	}

	// 没有命中静态库的内容，返回原始 itemList
	if staticAnswer == nil {
		return itemList
	}

	// 有命中静态库的内容，生成新的 itemList 返回
	respMessage := &proto.ChatMessage{
		MessageId:   requestCtx.GetBizContext().RespMessageId(),
		TimestampMs: time.Now().UnixMilli(),
		Type:        staticAnswer.GetBizItem().Type,
	}

	item := entities.ItemFromMessageByAnswer(respMessage)
	if staticAnswer.GetBizItem().GetSecurity().FAQ != "" {
		item.Text = staticAnswer.GetBizItem().GetSecurity().FAQ
		item.ChatRespType = proto.ChatRespType_FAQ
	} else if staticAnswer.GetBizItem().GetSecurity().RedLine != "" {
		item.Text = staticAnswer.GetBizItem().GetSecurity().RedLine
		item.ChatRespType = proto.ChatRespType_RED_LINE
	}

	resList := []*data_frame.ItemData[entities.Item]{
		item.IntoFrameItem(requestCtx),
	}

	return resList
}

func (q *StaticQAJudgeLogic) saveSecurityTracing(logCtx context.Context, hasSecurityPassedItem bool, security *model.Security, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
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
