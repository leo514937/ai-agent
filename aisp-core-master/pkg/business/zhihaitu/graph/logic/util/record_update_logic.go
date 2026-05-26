package util

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/censor/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type stopEnum string

func (s stopEnum) String() string {
	return string(s)
}

const (
	stopEnumBan  stopEnum = "BAN"
	stopEnumPass stopEnum = "PASS"
)

// RecordUpdateLogic 更新回答的状态记录问题和回答
// input[0]：AnswerSecurityReviewIsAvailable bool
// input[1]：RedLineAnswer string
// input[2]：ChatRespMessage *entities.Item
// input[3]：respMessageId string
// input[4]：FaqAnswer string
// output：无
type RecordUpdateLogic struct {
	*logic.BaseLogic[entities.RequestContext]
	chatService *service.ChatServiceImpl
}

func NewRecordUpdateLogic(name string, config map[string]string) *RecordUpdateLogic {
	l := &RecordUpdateLogic{
		BaseLogic:   logic.NewBaseLogic[entities.RequestContext](name, config),
		chatService: service.DefaultChatService,
	}
	l.RealDoFunc = l.updateAnswer
	return l
}

func (b *RecordUpdateLogic) updateAnswer(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	securityReviewIsAvailable, ok := requestCtx.DataMap().GetBool(ctx, b.GetInputName(0))
	redLineAnswer, _ := requestCtx.DataMap().GetString(ctx, b.GetInputName(1))
	chatMessage, chatMessageOk := requestCtx.DataMap().GetObjMap(ctx, b.GetInputName(2))
	respMessageId, _ := requestCtx.DataMap().GetString(ctx, b.GetInputName(3))
	faqAnswer, _ := requestCtx.DataMap().GetString(ctx, b.GetInputName(4))

	var content = constant.RefuseText
	var stop = stopEnumPass

	// 如果answer命中红线必答，忽略安全review结果
	if redLineAnswer != "" {
		content = redLineAnswer
	} else if faqAnswer != "" {
		content = faqAnswer
	} else if ok && securityReviewIsAvailable {
		if chatMessageOk {
			respMessage, respOk := chatMessage.(*proto.ChatMessage)
			if respOk {
				content = respMessage.Text
			}
		}
	}

	updates := map[string]interface{}{
		// 需要用update_time排序，为了防止和question一样，这里额外加1s
		"update_time": time.Now().Add(time.Second * 1),
		"state":       constant.MsgStateEnd,
		"content":     content,
		"stop_enum":   stop.String(),
	}

	log.Infof(ctx, "update answer record. respMessageId=%s, content=%s", respMessageId, content)

	err := b.chatService.UpdateMessage(ctx, respMessageId, updates)
	if err != nil {
		return err
	}
	return nil
}
