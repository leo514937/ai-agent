package operation_config

// MessageType 定义消息类型
type MessageType string

const (
	MessageTypePrompt  MessageType = "prompt"
	MessageTypeUnknown MessageType = "unknown"
)

// BaseMessage 基础消息结构
type BaseMessage struct {
	Type MessageType `json:"type"`
}

// PromptMessage 提示消息结构
type PromptMessage struct {
	Type                     MessageType `json:"type"`
	ModelName                string      `json:"model_name"`
	SystemPrompt             string      `json:"system_prompt"`
	UserPromptPureDocsPrompt string      `json:"user_prompt_pure_docs"`
	UserPromptCitationPrompt string      `json:"user_prompt_citation"`
}

// PromptDemo Demo
type PromptDemo struct {
	Type         MessageType `json:"type"`
	SystemPrompt string      `json:"system_prompt"`
}

// Message 通用消息接口
type Message interface {
	GetType() MessageType
}

// 实现 Message 接口
func (p *PromptMessage) GetType() MessageType {
	return p.Type
}

func (p *PromptDemo) GetType() MessageType {
	return p.Type
}
