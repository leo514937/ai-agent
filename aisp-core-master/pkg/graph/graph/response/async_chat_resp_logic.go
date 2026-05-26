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
)

// AsyncChatRespLogic 异步对话的结果
// input[0]: Question的安全review结果 bool
// input[1]: 红线必答的结果，如果没有命中红线必答，则为空 string
// input[2]: respMessageId string
// output[0]: 最终输出，类型：*proto.ChatResponse
type AsyncChatRespLogic struct {
	*logic.BaseLogic[entities.RequestContext]
}

func NewAsyncChatRespLogic(name string, config map[string]string) *AsyncChatRespLogic {
	res := &AsyncChatRespLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}

	res.RealDoFunc = res.buildResponse

	res.NeedSignal = true
	return res
}

func (q *AsyncChatRespLogic) buildResponse(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {

	refuseText := requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.RefuseText)

	questionSecurityReviewIsAvailable, questionOk := requestCtx.DataMap().GetBool(ctx, q.GetInputName(0))
	redLineAnswer, _ := requestCtx.DataMap().GetString(ctx, q.GetInputName(1))
	respMessageId, _ := requestCtx.DataMap().GetString(ctx, q.GetInputName(2))

	var chatResponse *proto.ChatResponse
	if redLineAnswer != "" {
		chatResponse = &proto.ChatResponse{
			State: proto.ChatState_PROCESSING,
			Message: &proto.ChatMessage{
				MessageId:   respMessageId,
				TimestampMs: time.Now().UnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        "",
			},
			RespType: proto.ChatRespType_RED_LINE,
		}
		log.Infof(ctx, "build response.  hit red line, resp text=%s", redLineAnswer)
	} else if questionOk && !questionSecurityReviewIsAvailable {
		chatResponse = &proto.ChatResponse{
			State: proto.ChatState_PROCESSING,
			Message: &proto.ChatMessage{
				MessageId:   respMessageId,
				TimestampMs: time.Now().UnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        refuseText,
			},
			RespType: proto.ChatRespType_REFUSE,
		}
		log.Infof(ctx, "build response.  questionSecurityReviewIsAvailable=false")
	} else {
		chatResponse = &proto.ChatResponse{
			State: proto.ChatState_PROCESSING,
			Message: &proto.ChatMessage{
				MessageId:   respMessageId,
				TimestampMs: time.Now().UnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        "",
			},
			RespType: proto.ChatRespType_DOMAIN,
		}
		log.Infof(ctx, "build response.  answerSecurityReviewIsAvailable=true")
	}

	requestCtx.DataMap().SetObjMap(ctx, q.GetOutputName(0), chatResponse)

	return nil
}
