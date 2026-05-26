package model

import "time"

type Task struct {
	ID                  int64             `json:"id"`
	TenantID            int64             `json:"tenant_id"`
	Name                string            `json:"name"`
	Owner               string            `json:"owner"`
	Description         string            `json:"description"`
	AIProfile           string            `json:"ai_profile"`
	PromptTemplateID    int64             `json:"prompt_template_id"`
	ModelEngineTaskName string            `json:"model_engine_task_name"`
	State               TaskState         `json:"state"`
	AuditMode           AuditMode         `json:"audit_mode"`
	ConversationModel   ConversationModel `json:"conversation_model"`
	RateLimit           int64             `json:"rate_limit"`
	CreatedAt           time.Time         `json:"created_at"`
	UpdatedAt           time.Time         `json:"updated_at"`
}

type TaskState string

const (
	TaskStateNormal  TaskState = "NORMAL"
	TaskStateDeleted TaskState = "DELETED"
)

type ConversationModel string

const (
	ConversationModelFreeConversation ConversationModel = "FREE_CONVERSATION"
	ConversationModelTask             ConversationModel = "TASK"
)

type AuditMode string

const (
	AuditModeNoFallback        AuditMode = "NO_FALLBACK"
	AuditModeFallbackToNotPass AuditMode = "FALLBACK_TO_NOT_PASS"
)
