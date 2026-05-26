package util

import (
	"context"
	"time"

	"git.in.zhihu.com/go/utils"
	zhihaitu_dao "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// ReportQuestionLogic 上报监管
// input[0]: memberId int64
// input[1]: sessionId string
// input[2]: messageId string
// input[3]: queryText string
// output: 无
type ReportQuestionLogic struct {
	*logic.BaseLogic[entities.RequestContext]
	openapiAccountDAO zhihaitu_dao.OpenapiAccountDAO
}

func NewReportQuestionLogic(name string, config map[string]string) *ReportQuestionLogic {
	l := &ReportQuestionLogic{
		BaseLogic:         logic.NewBaseLogic[entities.RequestContext](name, config),
		openapiAccountDAO: zhihaitu_dao.DefaultOpenapiAccountDAO,
	}
	l.RealDoFunc = l.report

	return l
}

func (r *ReportQuestionLogic) report(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "util.ReportAnswerLogic.report")
	defer span.Finish()
	span.LogFields(log.Message("start."))

	memberId, _ := requestCtx.DataMap().GetInt64(logCtx, r.GetInputName(0))
	sessionId, _ := requestCtx.DataMap().GetString(logCtx, r.GetInputName(1))
	messageId, _ := requestCtx.DataMap().GetString(logCtx, r.GetInputName(2))
	queryText, _ := requestCtx.DataMap().GetString(logCtx, r.GetInputName(3))

	userQuestion := &model.UserQuestion{
		ReportMsgHeader: model.ReportMsgHeader{
			MsgType: model.MsgTypeUserQuestion,
		},
		QuestionID:  messageId,
		Content:     queryText,
		UserID:      cast.ToString(memberId),
		State:       model.UserQuestionStateQuestion,
		SessionID:   sessionId,
		PublishTime: time.Now().Format("20060102150405"),
	}

	account, err := r.openapiAccountDAO.GetByMemberId(ctx, memberId)
	if err == nil && account.Role != model.RoleAdmin {
		log.Info(ctx, "report data", lo.Must(utils.MarshalToString(userQuestion)))
		model.SendData(ctx, userQuestion)
	} else {
		log.Info(ctx, "admin skip send message")
	}
	return nil
}
