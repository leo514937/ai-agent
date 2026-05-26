package util

import (
	"context"
	"time"

	"git.in.zhihu.com/go/utils"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	zhihaitu_dao "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// ReportAnswerLogic 上报监管
// input[0]: sessionId string
// input[1]: messageId string
// input[2]: respMessageId string
// input[3]: chatRespMessage *proto.ChatMessage
// input[4]: memberId int64
// input[5]: redlineAnswer string
// input[6]: securityReviewIsAvailable bool
// input[7]: faqAnswer string
// output: 无
type ReportAnswerLogic struct {
	*logic.BaseLogic[entities.RequestContext]
	openapiAccountDAO zhihaitu_dao.OpenapiAccountDAO
}

func NewReportAnswerLogic(name string, config map[string]string) *ReportAnswerLogic {
	l := &ReportAnswerLogic{
		BaseLogic:         logic.NewBaseLogic[entities.RequestContext](name, config),
		openapiAccountDAO: zhihaitu_dao.DefaultOpenapiAccountDAO,
	}
	l.RealDoFunc = l.report

	return l
}

func (r *ReportAnswerLogic) report(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "util.ReportAnswerLogic.report")
	defer span.Finish()
	span.LogFields(log.Message("start."))

	sessionId, _ := requestCtx.DataMap().GetString(logCtx, r.GetInputName(0))
	messageId, _ := requestCtx.DataMap().GetString(logCtx, r.GetInputName(1))
	respMessageId, _ := requestCtx.DataMap().GetString(logCtx, r.GetInputName(2))
	chatRespMessage, ok := requestCtx.DataMap().GetObjMap(logCtx, r.GetInputName(3))
	memberId, _ := requestCtx.DataMap().GetInt64(logCtx, r.GetInputName(4))
	redLineAnswer, _ := requestCtx.DataMap().GetString(ctx, r.GetInputName(5))
	securityReviewIsAvailable, securityReviewIsAvailableOk := requestCtx.DataMap().GetBool(ctx, r.GetInputName(6))
	faqAnswer, _ := requestCtx.DataMap().GetString(ctx, r.GetInputName(7))

	var content = constant.RefuseText
	if redLineAnswer != "" {
		content = redLineAnswer
	} else if faqAnswer != "" {
		content = faqAnswer
	} else if ok {
		// 有可能没有产生answer
		respMessage, respOk := chatRespMessage.(*proto.ChatMessage)
		if securityReviewIsAvailable && securityReviewIsAvailableOk && respOk {
			content = respMessage.Text
		}
	}

	aiAnswer := &model.AIAnswer{
		ReportMsgHeader: model.ReportMsgHeader{
			MsgType: model.MsgTypeAIAnswer,
		},
		AnswerID:       respMessageId,
		QuestionID:     messageId,
		SessionID:      sessionId,
		PublishTime:    time.Now().Format("20060102150405"),
		RegenerateType: model.AiAnswerRegenerateTypeFirst,
		Content:        content,
	}

	account, err := r.openapiAccountDAO.GetByMemberId(ctx, memberId)
	if err == nil && account.Role != model.RoleAdmin {
		log.Info(ctx, "report data", lo.Must(utils.MarshalToString(aiAnswer)))
		model.SendData(ctx, aiAnswer)
	} else {
		log.Info(ctx, "admin, skip report message")
	}

	return nil
}
