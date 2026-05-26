package response

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// BuildChatResponseBaseLogic 构造*proto.ChatResponse类型的最终结果
// input[0]: Question的安全review结果 bool
// input[1]: Answer的安全review结果 bool
// input[2]: 红线必答的结果，如果没有命中红线必答，则为空 string
// input[3]: respMessageId string
// input[4]: 对话的结果 *proto.ChatMessage
// output[0]: 最终输出，类型：*proto.ChatResponse
type BuildChatResponseBaseLogic struct {
	*logic.BaseLogic[entities.RequestContext]
}

func NewBuildChatResponseBaseLogic(name string, config map[string]string) *BuildChatResponseBaseLogic {
	res := &BuildChatResponseBaseLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}
	res.RealExecFunc = res.buildResponse
	res.NeedSignal = false

	return res
}

func (b *BuildChatResponseBaseLogic) buildResponse(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	refuseText := requestCtx.GetBizContext().GetLogicConfig(b.GetName(), conf.RefuseText)

	questionSecurityReviewIsAvailable, questionOk := requestCtx.DataMap().GetBool(ctx, b.GetInputName(0))
	answerSecurityReviewIsAvailable, answerOk := requestCtx.DataMap().GetBool(ctx, b.GetInputName(1))
	redLineAnswer, _ := requestCtx.DataMap().GetString(ctx, b.GetInputName(2))
	respMessageId, _ := requestCtx.DataMap().GetString(ctx, b.GetInputName(3))
	chatMessage, ok := requestCtx.DataMap().GetObjMap(ctx, b.GetInputName(4))
	faqAnswer, _ := requestCtx.DataMap().GetString(ctx, b.GetInputName(5))

	var respMessage *proto.ChatMessage = nil
	if ok {
		respMessage, _ = chatMessage.(*proto.ChatMessage)
	}

	var chatResponse *proto.ChatResponse
	if redLineAnswer != "" || faqAnswer != "" {
		answerText := lo.Ternary(faqAnswer != "", faqAnswer, redLineAnswer)
		chatResponse = &proto.ChatResponse{
			State: proto.ChatState_COMPLETED,
			Message: &proto.ChatMessage{
				MessageId:   respMessageId,
				TimestampMs: time.Now().UnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        answerText,
			},
			RespType: proto.ChatRespType_RED_LINE,
		}
		log.Infof(ctx, "build response.  hit red line, resp text=%s", redLineAnswer)
	} else if questionOk && !questionSecurityReviewIsAvailable {
		chatResponse = &proto.ChatResponse{
			State: proto.ChatState_COMPLETED,
			Message: &proto.ChatMessage{
				MessageId:   respMessageId,
				TimestampMs: time.Now().UnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        refuseText,
			},
			RespType: proto.ChatRespType_REFUSE,
		}
		log.Infof(ctx, "build response.  questionSecurityReviewIsAvailable=false")
	} else if answerOk && answerSecurityReviewIsAvailable {
		text := refuseText
		if respMessage != nil {
			text = respMessage.Text
		}
		chatResponse = &proto.ChatResponse{
			State: proto.ChatState_COMPLETED,
			Message: &proto.ChatMessage{
				MessageId:   respMessageId,
				TimestampMs: time.Now().UnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        text,
			},
			RespType: proto.ChatRespType_DOMAIN,
		}
		log.Infof(ctx, "build response.  answerSecurityReviewIsAvailable=true, resp text=%s", text)
	} else {
		chatResponse = &proto.ChatResponse{
			State: proto.ChatState_COMPLETED,
			Message: &proto.ChatMessage{
				MessageId:   respMessageId,
				TimestampMs: time.Now().UnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        refuseText,
			},
			RespType: proto.ChatRespType_REFUSE,
		}
		log.Infof(ctx, "build response.  answerSecurityReviewIsAvailable=false")
	}

	requestCtx.DataMap().SetObjMap(ctx, b.GetOutputName(0), chatResponse)

	return nil
}
