package util

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/censor/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	zhihaitu_model "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// RecordLogic 记录问题和回答
// input[0]：sessionId string
// input[1]: memberId string
// input[2]: messageId int64
// input[3]: parentMessageId string
// input[4]: content string
// output：无
type RecordLogic struct {
	*logic.BaseLogic[entities.RequestContext]
	chatService *service.ChatServiceImpl
}

func NewRecordLogic(name string, config map[string]string) *RecordLogic {
	l := &RecordLogic{
		BaseLogic:   logic.NewBaseLogic[entities.RequestContext](name, config),
		chatService: service.DefaultChatService,
	}
	l.RealDoFunc = l.record
	return l
}

func (b *RecordLogic) record(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "util.RecordLogic.record")
	defer span.Finish()
	span.LogFields(log.Message("start."))

	recordType := conf.MessageType(requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.ConfigMessageType))

	var err error
	if recordType == conf.MessageTypeQuestion {
		err = b.recordQuestion(ctx, requestCtx)
	} else if recordType == conf.MessageTypeAnswer {
		err = b.recordInitAnswer(ctx, requestCtx)
	}

	if err != nil {
		return err
	}

	return nil
}

func (b *RecordLogic) recordQuestion(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "util.RecordLogic.recordQuestion")
	defer span.Finish()

	sessionId, _ := requestCtx.DataMap().GetString(logCtx, b.GetInputName(0))
	memberId, _ := requestCtx.DataMap().GetInt64(logCtx, b.GetInputName(1))
	messageId, _ := requestCtx.DataMap().GetString(logCtx, b.GetInputName(2))
	parentMessageId, _ := requestCtx.DataMap().GetString(logCtx, b.GetInputName(3))
	content, _ := requestCtx.DataMap().GetString(logCtx, b.GetInputName(4))

	now := time.Now()
	message := &zhihaitu_model.TableBmbConvMessage{
		ConvID:         sessionId,
		CreateTime:     now,
		UpdateTime:     now,
		MsgID:          messageId,
		Role:           constant.ChatRoleUser,
		Content:        content,
		ParentMsgID:    parentMessageId,
		CostTimeMillis: 0,
		MsgType:        "conv",
		ImageID:        nil,
		State:          constant.MsgStateEnd,
		AppID:          constant.ZhiHaiTuAppID,
		IsDeleted:      zhihaitu_model.NotDeleted,
	}
	err := b.chatService.RecordMessage(ctx, memberId, message)
	if err != nil {
		return err
	}
	return nil
}

func (b *RecordLogic) recordInitAnswer(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "util.RecordLogic.recordInitAnswer")
	defer span.Finish()

	sessionId, _ := requestCtx.DataMap().GetString(logCtx, b.GetInputName(0))
	memberId, _ := requestCtx.DataMap().GetInt64(logCtx, b.GetInputName(1))
	messageId, _ := requestCtx.DataMap().GetString(logCtx, b.GetInputName(2))
	parentMessageId, _ := requestCtx.DataMap().GetString(logCtx, b.GetInputName(3))

	var content = ""

	now := time.Now()
	message := &zhihaitu_model.TableBmbConvMessage{
		ConvID:         sessionId,
		CreateTime:     now,
		UpdateTime:     now,
		MsgID:          messageId,
		Role:           constant.ChatRoleAi,
		Content:        content,
		ParentMsgID:    parentMessageId,
		CostTimeMillis: 0,
		MsgType:        "conv",
		ImageID:        nil,
		State:          constant.MsgStateNotStarted,
		AppID:          constant.ZhiHaiTuAppID,
		IsDeleted:      zhihaitu_model.NotDeleted,
	}

	err := b.chatService.RecordMessage(ctx, memberId, message)

	if err != nil {
		return err
	}
	return nil
}
