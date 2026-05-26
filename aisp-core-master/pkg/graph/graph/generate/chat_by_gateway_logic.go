package generate

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

// ChatByModelGatewayLogic 请求模型生成内容
// input[0]: generatedPrompt []*dto.ChatRequestMessage
// input[1]: respMessageId string
// output[0]: answer *proto.ChatMessage
type ChatByModelGatewayLogic struct {
	*logic.BaseLogic[entities.RequestContext]
	modelGatewayRPC modelapi.ModelTarget
}

func NewChatByModelGatewayLogic(name string, config map[string]string) *ChatByModelGatewayLogic {
	res := &ChatByModelGatewayLogic{
		BaseLogic:       logic.NewBaseLogic[entities.RequestContext](name, config),
		modelGatewayRPC: rpc.DefaultModelGatewayRouter,
	}

	res.RealDoFunc = res.chat
	return res
}

func (c *ChatByModelGatewayLogic) chat(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "generate.ChatByModelGatewayLogic.chat")
	defer span.Finish()
	span.LogFields(log.Message("start."))

	modelName := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ConfigModelName)

	generatedPrompt, ok := requestCtx.DataMap().GetObjMap(logCtx, c.GetInputName(0))
	respMessageId, _ := requestCtx.DataMap().GetString(logCtx, c.GetInputName(1))
	if !ok {
		log.Errorf(ctx, "generatedPrompt is nil")
		return nil
	}

	messages := generatedPrompt.([]*dto.ChatRequestMessage)

	messages = c.mergeHistoryAndQuery(requestCtx, messages)

	log.Infof(ctx, "llm chat messages:%v", util.GetJSONIgnoreError(messages))

	var req = &dto.ChatRequest{
		ModelName: modelName,
		AIProfile: "",
		Messages:  messages,
	}
	response, err := c.modelGatewayRPC.Chat(ctx, req)

	if err != nil {
		log.Errorf(ctx, "failed to chat with model gateway. err: %+v", err)
		return err
	}

	log.Infof(ctx, "llm chat response:%v", util.GetJSONIgnoreError(response))

	content := response.Content

	chatMessage := &proto.ChatMessage{
		MessageId:   respMessageId,
		TimestampMs: time.Now().UnixMilli(),
		Type:        proto.ChatMessageType_TEXT,
		Text:        content,
	}

	requestCtx.DataMap().SetObjMap(logCtx, c.GetOutputName(0), chatMessage)

	return nil
}

func (c *ChatByModelGatewayLogic) mergeHistoryAndQuery(
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], messages []*dto.ChatRequestMessage) []*dto.ChatRequestMessage {
	chatHistory := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ConfigChatHistoryKey))

	if chatHistory {
		messages = append(messages, message.HistToChatRequestMessage(requestCtx.GetBizContext().GetHistoryDialogue())...)
	}

	return messages
}
