package model

import "time"

type Conversation struct {
	ID        int64             `json:"id"`
	TenantID  int64             `json:"tenant_id"`
	TaskID    int64             `json:"task_id"`
	CreatorID string            `json:"creator_id"`
	State     ConversationState `json:"state"`
	System    map[string]any    `json:"system"`
	CreatedAt time.Time         `json:"created_at"`
	UpdatedAt time.Time         `json:"updated_at"`
}

type ConversationState string

const (
	ConversationStateNormal  ConversationState = "NORMAL"
	ConversationStateDeleted ConversationState = "DELETED"
)
