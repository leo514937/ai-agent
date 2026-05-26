package dialogue

import "context"

//go:generate mockery --name ContentModerator
type ContentModerator interface {
	// Review 会对对话进行审核，返回审核结果和原因. 如果审核结果为 ReviewResultPass, 则 reason, err 为空
	Review(ctx context.Context, request *ReviewRequest) (result ReviewResult, reason string, err error)
}

type ReviewResult string

const (
	ReviewResultPass    ReviewResult = "PASS"
	ReviewResultNotPass ReviewResult = "NOT_PASS"
)

var DefaultContentModerator ContentModerator

type ReviewRequest struct {
	TenantID       int64
	TaskID         int64
	UserID         string
	ConversationID int64
	DialogueID     int64
	UserMessage    string
	AIMessage      string
	History        []*HistoryEntry
}

type HistoryEntry struct {
	DialogueID  int64
	UserMessage string
	AIMessage   string
}
