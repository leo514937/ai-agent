package model

import "time"

type DialogRecord struct {
	ID              int64     `json:"id" borm:"primary_key"`
	RoleType        string    `json:"role_type"`                  // 角色类型 USER AI
	Scene           string    `json:"scene"`                      // 场景 AI_TAB SEARCH_TAB
	MemberId        int64     `json:"member_id"`                  // 用户Id
	AiId            int64     `json:"ai_id"`                      // AI Id
	SessionId       int64     `json:"session_id"`                 // 会话Id
	ConversationId  string    `json:"conversation_id"`            // 场景 AI_TAB SEARCH_TAB
	MessageGroupId  string    `json:"message_group_id"`           // 消息组Id（主要用于修改标题和重答）
	MessageId       string    `json:"message_id"`                 // 消息Id
	ParentMessageId string    `json:"parent_message_id"`          // 父级消息Id
	MessageContent  string    `json:"message_content" borm:""`    // 消息文本 当消息类型为文本时有效
	MessageType     int64     `json:"message_type"`               // 消息类型 0:未知 1:文本
	RecordAt        time.Time `json:"record_at"`                  // 消息创建时间
	CreateType      int64     `json:"create_type"`                // 创建类型 0未知 1:用户输入 2:静态库输出 3:LLM输出
	ErrorType       int64     `json:"error_type"`                 // 异常类型 0:正常 安全拒答 安全兜底 LLM兜底
	Exceeded        int64     `json:"exceeded"`                   // 是否过期 0否 1是
	Deleted         int64     `json:"deleted"`                    // 是否删除 0否 1是
	CreatedAt       time.Time `json:"created_at" borm:"readonly"` // 创建时间 设置borm只读，利用数据库的能力生成 CreatedAt
	UpdatedAt       time.Time `json:"updated_at" borm:"readonly"` // 修改时间 设置borm只读，利用数据库的能力生成 CreatedAt
}

func (d *DialogRecord) ToConvert() *DialogRecordInsertDto {
	return &DialogRecordInsertDto{
		RoleType:        d.RoleType,
		Scene:           d.Scene,
		MemberId:        d.MemberId,
		AiId:            d.AiId,
		SessionId:       d.SessionId,
		ConversationId:  d.ConversationId,
		MessageId:       d.MessageId,
		ParentMessageId: d.ParentMessageId,
		MessageContent:  d.MessageContent,
		MessageType:     d.MessageType,
		RecordAt:        d.RecordAt,
		CreateType:      d.CreateType,
		ErrorType:       d.ErrorType,
	}
}

func (d *DialogRecord) IsError() bool {
	return d.ErrorType != DialogErrorTypeNormal.ToConvert()
}

type DialogRecordInsertDto struct {
	RoleType        string    `json:"role_type"`         // 角色类型 USER AI
	Scene           string    `json:"scene"`             // 场景 AI_TAB SEARCH_TAB
	MemberId        int64     `json:"member_id"`         // 用户Id
	AiId            int64     `json:"ai_id"`             // AI Id
	SessionId       int64     `json:"session_id"`        // 会话Id
	ConversationId  string    `json:"conversation_id"`   // 场景 AI_TAB SEARCH_TAB
	MessageId       string    `json:"message_id"`        // 消息Id
	ParentMessageId string    `json:"parent_message_id"` // 父级消息Id
	MessageContent  string    `json:"message_content"`   // 消息文本 当消息类型为文本时有效
	MessageType     int64     `json:"message_type"`      // 消息类型 0:未知 1:文本
	RecordAt        time.Time `json:"record_at"`         // 消息创建时间
	CreateType      int64     `json:"create_type"`       // 创建类型 0未知 1:用户输入 2:静态库输出 3:LLM输出
	ErrorType       int64     `json:"error_type"`        // 异常类型 0:正常 安全拒答 安全兜底 LLM兜底
}

// RoleType 消息类型
type RoleType string

func (t RoleType) ToConvert() string {
	return string(t)
}

const (
	// RoleTypeUser 角色类型 用户
	RoleTypeUser RoleType = "USER"
	// RoleTypeAI 角色类型 AI
	RoleTypeAI RoleType = "AI"
)

// DialogCreateType 创建类型
type DialogCreateType int64

func (t DialogCreateType) ToConvert() int64 {
	return int64(t)
}

const (
	// DialogCreateTypeUnknown 消息常见类型 未知
	DialogCreateTypeUnknown DialogCreateType = 0
	// DialogCreateTypeInput 消息类型 用户输入
	DialogCreateTypeInput DialogCreateType = 1
	// DialogCreateTypeStaticLib 消息类型 静态库输出
	DialogCreateTypeStaticLib DialogCreateType = 2
	// DialogCreateTypeLLM 消息类型 LLM输出
	DialogCreateTypeLLM DialogCreateType = 3
	// DialogCreateTypeTmp 消息类型 临时
	DialogCreateTypeTmp DialogCreateType = 4
)

// DialogErrorType 异常类型
type DialogErrorType int64

func (t DialogErrorType) ToConvert() int64 {
	return int64(t)
}

const (
	// DialogErrorTypeNormal 异常类型 正常
	DialogErrorTypeNormal DialogErrorType = 0
	// DialogErrorTypeSecurityRejection 异常类型 安全拒绝
	DialogErrorTypeSecurityRejection DialogErrorType = 1
	// DialogErrorTypeSecurityCover 异常类型 安全兜底
	DialogErrorTypeSecurityCover DialogErrorType = 2
	// DialogErrorTypeLLMCover 消息类型 LLM兜底
	DialogErrorTypeLLMCover DialogErrorType = 3
	// DialogErrorTypeRedLine 消息类型 红线必答
	DialogErrorTypeRedLine DialogErrorType = 4
	// DialogErrorTypeFaq 消息类型 faq
	DialogErrorTypeFaq DialogErrorType = 5
	// DialogErrorTypeUnknown 消息类型 未知
	DialogErrorTypeUnknown DialogErrorType = 99
)
