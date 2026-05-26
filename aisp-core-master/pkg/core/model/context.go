package model

type Context struct {
	AIProfile       string
	UserProfile     string
	Prompt          string
	RecentMessages  []*Message
	HistoryMessages []*Message
}

type Message struct {
	Role    MessageRole
	Content string
}

type MessageRole string

const (
	MessageRoleUser MessageRole = "USER"
	MessageRoleAI   MessageRole = "AI"
)
