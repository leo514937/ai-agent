package model

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

var roleTypeOpenaiMap = map[dto.ChatRequestMessageRole]proto.RoleOpenAi{
	dto.ChatRequestMessageRoleUser: proto.RoleOpenAi_user,
	dto.ChatRequestMessageRoleAI:   proto.RoleOpenAi_assistant,
}

func ChatRequestMessages2Messages(systemPrompt string, chatRequestMessages []*dto.ChatRequestMessage) []*proto.MessageOpenai {
	messages := []*proto.MessageOpenai{
		{
			Role:    proto.RoleOpenAi_system,
			Content: systemPrompt,
		},
	}
	for _, chatRequestMessage := range chatRequestMessages {
		messages = append(messages, &proto.MessageOpenai{
			Role:    roleTypeOpenaiMap[chatRequestMessage.Role],
			Content: chatRequestMessage.Content,
		})
	}
	return messages
}

func ChatRequestMessages2MessagesBySource(chatRequestMessages []*dto.ChatRequestMessage) []*proto.MessageOpenai {
	messages := make([]*proto.MessageOpenai, 0)
	for _, chatRequestMessage := range chatRequestMessages {
		messages = append(messages, &proto.MessageOpenai{
			Role:    roleTypeOpenaiMap[chatRequestMessage.Role],
			Content: chatRequestMessage.Content,
		})
	}
	return messages
}

func ChatRequest2LlmParam(request *dto.ChatRequest) *proto.ModelArgs {
	return &proto.ModelArgs{
		MaxTokens:          util.Int32ToWrapperspbInt32(request.MaxTokens),
		Stop:               request.Stop,
		Temperature:        util.Float32ToWrapperspbFloat(request.Temperature),
		TopP:               util.Float32ToWrapperspbFloat(request.TopP),
		TopK:               util.Int32ToWrapperspbInt32(request.TopK),
		PresencePenalty:    util.Float32ToWrapperspbFloat(request.PresencePenalty),
		FrequencyPenalty:   util.Float32ToWrapperspbFloat(request.FrequencyPenalty),
		RepetitionPenalty:  util.Float32ToWrapperspbFloat(request.RepetitionPenalty),
		PreviousResponseId: request.PreviousResponseId,
	}
}
