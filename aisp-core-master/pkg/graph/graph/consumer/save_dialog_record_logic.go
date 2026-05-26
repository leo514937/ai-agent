package consumer

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	dialogService "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/dialog_record"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// SaveDialogRecordLogic 保存对话历史到数据库中
// @logicAuthor: zhoupengcheng
// @logicInfo: 保存对话记录
// @logicInput: 0 | currentQuery *model.DialogRecord
// @logicInput: 1 | currentAnswer *model.DialogRecord
// @logicInput: 2 | query redLine answer, string
// @logicInput: 3 | query merge redLine answer, string
// @logicInput: 4 | query faq answer, string
// @logicInput: 5 | query merge faq answer, string
// @logicInput: 6 | query security review, bool
// @logicInput: 7 | query merge security review, bool
type SaveDialogRecordLogic struct {
	*logic.BaseLogic[entities.RequestContext]
	dialogRecordService dialogService.DialogService
}

func NewSaveDialogRecordLogic(name string, config map[string]string) *SaveDialogRecordLogic {
	res := &SaveDialogRecordLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}
	res.dialogRecordService = dialogService.NewDefaultDialogService()
	res.RealDoFunc = res.consume
	res.NeedSignal = true
	return res
}

func (s *SaveDialogRecordLogic) consume(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "consumer.SaveDialogRecordLogic.consume")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogMemberId(requestCtx.GetBizContext().MemberId()))

	// 开关控制是否落对话历史，开发调试时开启
	if requestCtx.GetBizContext().GetRunCaseConfig().IsOpen {
		return nil
	}

	query, queryOk := requestCtx.DataMap().GetObjMap(logCtx, s.GetInputName(0))
	answer, answerOk := requestCtx.DataMap().GetObjMap(logCtx, s.GetInputName(1))
	queryRedLineAnswer, _ := requestCtx.DataMap().GetString(logCtx, s.GetInputName(2))
	queryMergeRedLineAnswer, _ := requestCtx.DataMap().GetString(logCtx, s.GetInputName(3))
	queryFaqAnswer, _ := requestCtx.DataMap().GetString(logCtx, s.GetInputName(4))
	queryMergeFaqAnswer, _ := requestCtx.DataMap().GetString(logCtx, s.GetInputName(5))
	querySecurityReviewAvailable, querySecurityReviewOk := requestCtx.DataMap().GetBool(logCtx, s.GetInputName(6))
	queryMergeSecurityReviewAvailable, queryMergeSecurityReviewOk := requestCtx.DataMap().GetBool(logCtx, s.GetInputName(7))

	var dialogueQuery *model.DialogRecord
	var dialogueAnswer *model.DialogRecord
	if queryOk {
		dialogueQuery = query.(*model.DialogRecord)
	}
	if answerOk {
		dialogueAnswer = answer.(*model.DialogRecord)
	}

	// 这里逻辑是和 security_post.updateDialogCache 中的逻辑一致的
	if dialogueQuery != nil {
		if queryRedLineAnswer != "" || queryMergeRedLineAnswer != "" {
			dialogueQuery.ErrorType = model.DialogErrorTypeRedLine.ToConvert()
		} else if querySecurityReviewOk && !querySecurityReviewAvailable || queryMergeSecurityReviewOk && !queryMergeSecurityReviewAvailable {
			dialogueQuery.ErrorType = model.DialogErrorTypeSecurityRejection.ToConvert()
		} else if queryFaqAnswer != "" || queryMergeFaqAnswer != "" {
			dialogueQuery.ErrorType = model.DialogErrorTypeFaq.ToConvert()
		}
	}

	baseDialogue := requestCtx.GetBizContext().GetCurrentDialogue()
	var tmpDialogue message.DialogueWrapper
	cErr := util.DeepCopyByJSON(&tmpDialogue, baseDialogue)
	if cErr != nil || dialogueQuery == nil {
		return cErr
	}

	tmpDialogue.Query.RecordAt = dialogueQuery.RecordAt
	if util.GetJSONIgnoreError(tmpDialogue.Query) != util.GetJSONIgnoreError(dialogueQuery) {
		log.Errorf(ctx, "current dialogue query error. baseDialogue:%s, query:%s",
			util.GetJSONIgnoreError(tmpDialogue.Query), util.GetJSONIgnoreError(dialogueQuery))
	} else if util.GetJSONIgnoreError(tmpDialogue.Answer) != util.GetJSONIgnoreError(dialogueAnswer) {
		log.Errorf(ctx, "current dialogue answer error. baseDialogue:%s, query:%s, answer:%s",
			util.GetJSONIgnoreError(tmpDialogue.Answer), util.GetJSONIgnoreError(dialogueAnswer))
	}

	if dialogueQuery.MessageId == "" {
		log.Warnf(ctx, "SaveDialogRecordLogic: The session record cannot be saved because the messageId is empty, dialogue => %+v ", dialogueQuery)
		return nil
	}

	dialogue := &message.DialogueWrapper{
		Query:  dialogueQuery,
		Answer: dialogueAnswer,
	}

	log.Infof(ctx, "SaveDialogRecordLogic consume dialogue: %+v ", dialogue)
	_, err := s.dialogRecordService.SaveOrUpdateDialogWrapper(ctx, dialogue)

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(dialogue))
	constant.DataOutputNodeLog.Infof(logCtx, "err:%v", err)

	return err
}
