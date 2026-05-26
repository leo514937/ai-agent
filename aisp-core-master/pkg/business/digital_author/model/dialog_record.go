package model

type DialogRecordKafkaMsg struct {
	ConversationId string `json:"conversation_id"`
	MessageId      string `json:"message_id"`
	MemberId       string `json:"member_id"`
	Text           string `json:"text"`
	Role           Role   `json:"role"`
	Scene          Scene  `json:"scene"`
	TimeStampMs    int64  `json:"time_stamp_ms"`
}

type Role string

const (
	UserRole Role = "USER"
	AIRole   Role = "AI"
)

type Scene string

const (
	DigitalAuthor Scene = "DIGITAL_AUTHOR"
)
