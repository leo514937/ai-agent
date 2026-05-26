package model

import "time"

type Dialogue struct {
	ID               int64                  `json:"id"`
	TenantID         int64                  `json:"tenant_id"`
	TaskID           int64                  `json:"task_id"`
	ConversationID   int64                  `json:"conversation_id"`
	UserID           string                 `json:"user_id"`
	UserMessage      string                 `json:"user_message"`
	AIMessage        string                 `json:"ai_message"`
	Custom           map[string]interface{} `json:"custom"`
	Context          *Context               `json:"context"`
	InputTokenCount  int64                  `json:"input_token_count"`
	OutputTokenCount int64                  `json:"output_token_count"`
	State            DialogueState          `json:"state"`
	AuditState       DialogueAuditState     `json:"audit_state"`
	AuditReason      string                 `json:"audit_reason"`
	CreatedAt        time.Time              `json:"created_at"`
	UpdatedAt        time.Time              `json:"updated_at"`
}

type DialogueState string

const (
	DialogueStateProcessing DialogueState = "PROCESSING"
	DialogueStateSuccess    DialogueState = "SUCCESS"
	DialogueStateFail       DialogueState = "FAIL"
)

type DialogueAuditState string

const (
	DialogueAuditStateUnset              DialogueAuditState = "UNSET"
	DialogueAuditStateUserMessageNotPass DialogueAuditState = "USER_MESSAGE_NOT_PASS"
	DialogueAuditStateAIMessageNotPass   DialogueAuditState = "AI_MESSAGE_NOT_PASS"
	DialogueAuditStatePass               DialogueAuditState = "PASS"
)

type RequestEnv struct {
	Headers map[string][]string `json:"headers"`
}

type DialogueResult struct {
	AIMessage        *string
	Context          *string
	State            *DialogueState
	AuditState       *DialogueAuditState
	AuditReason      *string
	InputTokenCount  *int64
	OutputTokenCount *int64
}
