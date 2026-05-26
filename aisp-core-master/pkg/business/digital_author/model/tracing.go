package model

// 有业务方依赖，如果变更需要同步 yaojingwei
type TracingKafkaMsg struct {
	MessageId       string             `json:"message_id"`
	Security        SecurityCode       `json:"security"`
	Intention       string             `json:"intention"`
	TaskId          int64              `json:"task_id"`
	RecallKnowledge []*RecallKnowledge `json:"recall_knowledge"`
	QueryMerge      string             `json:"query_merge"`
}

type SecurityCode string

const (
	RedLineCode      SecurityCode = "RED_LINE"
	ReviewFailedCode SecurityCode = "REVIEW_FAILED"
	NormalCode       SecurityCode = "NORMAL"
)
