package conf

type MessageHandlerType string

const (
	// MsgElementBySystem System
	MsgElementBySystem MessageHandlerType = "system"
	// MsgElementByKnowledgeContext 召回内容知识库
	MsgElementByKnowledgeContext MessageHandlerType = "knowledge_context"
	// MsgElementByContextAssistantResponse 虚拟模型回答
	MsgElementByContextAssistantResponse MessageHandlerType = "context_assistant_response"
	// MsgElementByElementQuery 原始用户Query
	MsgElementByElementQuery MessageHandlerType = "query"
	// MsgElementByElementCustomQuery 自定义用户Query（可加模版）
	MsgElementByElementCustomQuery MessageHandlerType = "custom_query"
	// MsgElementByElementQueryOrQueryDefinition 原始用户Query-名词解释
	MsgElementByElementQueryOrQueryDefinition MessageHandlerType = "query_or_query_definition"
	// MsgElementByElementChatHistory 用户对话历史
	MsgElementByElementChatHistory MessageHandlerType = "chat_history"
)

type ChatMsgConfig struct {
	HandlerType           MessageHandlerType `json:"handler_type"`            // 处理消息类型
	PromptId              string             `json:"prompt_id"`               // prompt ID
	DefaultPromptTemplate string             `json:"default_prompt_template"` // 默认 prompt 模版
	AssistantText         string             `json:"assistant_text"`          // assistant 回答文本
	HistoryLimit          int                `json:"history_limit"`           // 历史对话条目数
	ContentLengthLimit    int                `json:"content_length_limit"`    // 内容长度限制
	PromptTag             string             `json:"prompt_tag"`              // prompt tag，会拼在 prompt_id 后面
}

func NewChatMsgConfigBySystem(promptId string, defaultPromptTemplate string, promptTag string) ChatMsgConfig {
	return ChatMsgConfig{
		HandlerType:           MsgElementBySystem,
		PromptId:              promptId,
		PromptTag:             promptTag,
		DefaultPromptTemplate: defaultPromptTemplate,
	}
}

func NewChatMsgConfigByKnowledge(promptId string, defaultPromptTemplate string, promptTag string) ChatMsgConfig {
	return ChatMsgConfig{
		HandlerType:           MsgElementByKnowledgeContext,
		PromptId:              promptId,
		PromptTag:             promptTag,
		DefaultPromptTemplate: defaultPromptTemplate,
	}
}

func NewChatMsgConfigByQuery() ChatMsgConfig {
	return ChatMsgConfig{
		HandlerType: MsgElementByElementQuery,
	}
}

func NewChatMsgConfigByCustomQuery(promptId string, defaultPromptTemplate string) ChatMsgConfig {
	return ChatMsgConfig{
		HandlerType:           MsgElementByElementCustomQuery,
		PromptId:              promptId,
		DefaultPromptTemplate: defaultPromptTemplate,
	}
}

func NewChatMsgConfigByQueryOrQueryDefinition(promptId string, defaultPromptTemplate string, promptTag string) ChatMsgConfig {
	return ChatMsgConfig{
		HandlerType:           MsgElementByElementQueryOrQueryDefinition,
		PromptId:              promptId,
		PromptTag:             promptTag,
		DefaultPromptTemplate: defaultPromptTemplate,
	}
}

func NewChatMsgConfigByChatHistory(historyLimit int) ChatMsgConfig {
	return NewChatMsgConfigByChatHistoryAndLimit(historyLimit, 10240)
}

func NewChatMsgConfigByChatHistoryAndLimit(historyLimit int, contentLengthLimit int) ChatMsgConfig {
	return ChatMsgConfig{
		HandlerType:        MsgElementByElementChatHistory,
		HistoryLimit:       historyLimit,
		ContentLengthLimit: contentLengthLimit,
	}
}

func NewChatMsgConfigByAssistantResponse(assistantText string) ChatMsgConfig {
	return ChatMsgConfig{
		HandlerType:   MsgElementByContextAssistantResponse,
		AssistantText: assistantText,
	}
}
