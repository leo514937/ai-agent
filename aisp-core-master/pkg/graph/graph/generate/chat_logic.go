package generate

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	baselog "git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 非流式对话算子

type ChatLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
	modelGatewayRPC modelapi.ModelTarget
	strLengthLimit  int
}

func NewChatLogic(name string, config map[string]string) *ChatLogic {
	res := &ChatLogic{
		MergeLogic:      merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
		modelGatewayRPC: rpc.DefaultModelGatewayRouter,
	}

	res.MergeFunc = res.chat

	// 字符串长度限制
	res.strLengthLimit = 2048

	return res
}

func (c *ChatLogic) getChatConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.ChatConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if configStr == "" {
		log.Errorf(ctx, "ChatLogic getChatConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), c.GetName()))
		return conf.ChatConfig{}
	}

	chatConfig := conf.ChatConfig{}
	err := json.Unmarshal([]byte(configStr), &chatConfig)
	if err != nil {
		log.Errorf(ctx, "ChatLogic getChatConfig error => config unmarshal error, config: %s, err: %v", configStr, err)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), c.GetName()))
		return conf.ChatConfig{}
	}

	if chatConfig.ModelName == "" {
		chatConfig.ModelName = entities.Luca80b0928
	}

	return chatConfig
}

func (c *ChatLogic) getChatMsgConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.MsgConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ChatMessageJsonConfig)
	if configStr == "" {
		log.Errorf(ctx, "ChatLogic getChatMsgConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), c.GetName()))
		return conf.MsgConfig{}
	}

	chatMsgConfig := conf.MsgConfig{}
	err := json.Unmarshal([]byte(configStr), &chatMsgConfig)
	if err != nil {
		log.Errorf(ctx, "ChatLogic getChatMsgConfig error => config is json unmarshal err")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), c.GetName()))
	}
	return chatMsgConfig
}

func (c *ChatLogic) chat(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	resp := make([]*data_frame.ItemData[entities.Item], 0)

	span, ctx, logCtx, cacheRespInterface := logic_context.InitLogicContext(ctx, requestCtx, c.GetName(), "generate.ChatLogic.chat")
	defer logic_context.DeferContext(span, c.GetName(), requestCtx, &resp)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	if cacheRespInterface != nil {
		cacheResp, isTypeOk := cacheRespInterface.([]*data_frame.ItemData[entities.Item])
		if isTypeOk {
			return cacheResp, nil
		}
	}

	isDisable := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ChatDisable)
	if cast.ToBool(isDisable) {
		return resp, nil
	}

	// span.LogFields(log.Message("ChatLogic chat start."), log.User(user), log.ItemLists(itemLists))
	chatMsgConfig := c.getChatMsgConfig(ctx, requestCtx)
	chatConfig := c.getChatConfig(ctx, requestCtx)

	startTime := time.Now().UnixMilli()
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "chat",
	})

	// 2024年11月06日11:15:54
	// 兼容旧模式 因为数字分身模块比较重 暂时先不改动这里
	var aiProfile string
	var messages []*dto.ChatRequestMessage
	if len(chatMsgConfig.MsgConfigArr) > 0 {
		aiProfile = chatConfig.AIProfile
		handlerConfigs := make([]conf.ChatMsgConfig, 0)
		handlerConfigs = append(handlerConfigs, conf.NewChatMsgConfigBySystem(chatMsgConfig.SystemPromptId, chatMsgConfig.SystemDefaultPromptTemplate, chatMsgConfig.SystemPromptTag))
		handlerConfigs = append(handlerConfigs, chatMsgConfig.MsgConfigArr...)
		messageHandler := NewMessageHandler(handlerConfigs, requestCtx, lo.Flatten(itemLists), int64(chatConfig.ContextLength), chatConfig.ExtraContextLength, *chatConfig.MaxTokens, false)
		// 处理数据
		// 1. 获取配置中的system信息，处理为system prompt
		systemPrompt, _, systemPromptErr := messageHandler.BuildPromptByDefPrompt(ctx,
			chatMsgConfig.SystemPromptId, chatMsgConfig.SystemDefaultPromptTemplate, chatMsgConfig.SystemPromptTag, "")
		if systemPromptErr == nil && systemPrompt != "" {
			aiProfile = systemPrompt
		}
		// 2. 将items 中清洗出召回内容 整理成知识库 并拼接为message
		messages = messageHandler.BuildMessages()
	} else {
		// 避免空list，先做合并
		var itemList []*data_frame.ItemData[entities.Item]
		for _, i := range itemLists {
			itemList = append(itemList, i...)
		}
		if len(itemList) == 0 {
			return itemList, nil
		}
		var query string
		for _, item := range itemList {
			if item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeQueryPrompt {
				query = item.GetBizItem().Text
			}
			if item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeSystemPrompt {
				aiProfile = item.GetBizItem().Text
			}
		}
		messages = c.mergeHistoryAndQuery(requestCtx, query, chatConfig)
	}

	req := &dto.ChatRequest{
		ModelName:         chatConfig.ModelName,
		AIProfile:         aiProfile,
		Messages:          messages,
		MaxTokens:         chatConfig.MaxTokens,
		Stop:              chatConfig.Stop,
		Temperature:       chatConfig.Temperature,
		TopP:              chatConfig.TopP,
		TopK:              chatConfig.TopK,
		RepetitionPenalty: chatConfig.RepetitionPenalty,
		EnableThinking:    chatConfig.EnableThinking,
	}

	if log.GetLevel() == baselog.DebugLevel {
		logger.Debugf(ctx, "llm chat messages:%v", util.GetJSONIgnoreError(req))
	}

	// span.LogFields(log.Message("modelGatewayRPC.Chat start."),
	// 	log.Json("req", req),
	// )
	response, err := c.modelGatewayRPC.Chat(ctx, req)

	span.LogFields(log.Message("modelGatewayRPC.Chat done."))

	if err != nil {
		logger.Errorf(ctx, "failed to chat with model gateway. err: %+v", err)
		return nil, err
	}
	content := response.Content
	respMessage := &proto.ChatMessage{
		MessageId:   requestCtx.GetBizContext().RespMessageId(),
		TimestampMs: time.Now().UnixMilli(),
		Type:        proto.ChatMessageType_TEXT,
		Text:        content,
	}
	item := entities.ItemFromMessageAndType(respMessage, entities.ChatMappingTypeLLMAnswer)
	item.ChatRespType = c.genChatRespType(requestCtx)

	resp = append(resp, item.IntoFrameItem(requestCtx))

	c.saveTracing(logCtx, req, content, startTime, requestCtx)
	c.saveAnswerTracing(content, requestCtx, chatConfig)
	// span.LogFields(log.Message("ChatLogic chat done."), log.Items(resp))
	return resp, nil
}

func (c *ChatLogic) saveTracing(logCtx context.Context, request *dto.ChatRequest, response string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   c.GetName(),
		LogicInput:  []string{util.GetJSONIgnoreError(request)},
		LogicOutput: []string{response},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(c.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(request))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", response)

}

func (c *ChatLogic) genChatRespType(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) proto.ChatRespType {
	intention := requestCtx.GetBizContext().GetIntention()

	switch intention.GetIntentionType() {
	case proto.IntentionType_IN_DOMAIN, proto.IntentionType_SEARCH_INTENTION:
		return proto.ChatRespType_DOMAIN
	case proto.IntentionType_OUT_DOMAIN, proto.IntentionType_NO_SEARCH_INTENTION:
		return proto.ChatRespType_NON_DOMAIN
	case proto.IntentionType_SMALL_TALKS, proto.IntentionType_AMBIGUOUS:
		return proto.ChatRespType_SMALL_TALK
	default:
		return proto.ChatRespType_UNKNOWN_RESP
	}
}

// handleHistoryDialogue 处理历史对话
func (c *ChatLogic) mergeHistoryAndQuery(
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], text string, chatConfig conf.ChatConfig) []*dto.ChatRequestMessage {
	messages := make([]*dto.ChatRequestMessage, 0)
	if chatConfig.IsNeedHistory {
		messages = append(messages, message.HistToChatRequestMessage(requestCtx.GetBizContext().GetHistoryDialogue())...)
	}

	//// 过滤对话历史 保持不超过 strLengthLimit 长度
	//if len(messages) > 0 {
	//	// 反转对话历史 保留里用户最近的历史内容
	//	reverseMessages := lo.Reverse(messages)
	//	// 最大不超过 strLengthLimit 长度的 历史对话
	//	chunkMessages := util.ChunkArrWithLimitStrLength(reverseMessages, c.strLengthLimit, func(item *dto.ChatRequestMessage) string {
	//		return item.Content
	//	})
	//	messages = lo.Reverse(chunkMessages)
	//}

	messages = append(messages, &dto.ChatRequestMessage{
		Content: text,
		Role:    dto.ChatRequestMessageRoleUser,
	})
	return messages
}

func (c *ChatLogic) saveAnswerTracing(answer string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], chatConfig conf.ChatConfig) {
	answerRecord := &proto.LLMAnswer{
		Stage:  chatConfig.Stage,
		Answer: answer,
	}

	answerChan := requestCtx.GetBizContext().ProcessTracing().LlmAnswer
	if len(answerChan) < entities.MaxTracingChanSize {
		answerChan <- answerRecord
	}
}
