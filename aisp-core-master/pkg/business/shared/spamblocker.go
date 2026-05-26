package shared

import (
	"context"
)

type SpamBlocker interface {
	IsSpam(ctx context.Context, tenantID int64, taskID int64, userID string, conversationID int64, userMessage string, environment Headers) (bool, error)
}

type Headers map[string][]string

var DefaultSpamBlocker SpamBlocker
