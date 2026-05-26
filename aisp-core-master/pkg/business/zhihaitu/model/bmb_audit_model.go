package model

import "time"

type ComplainedEnum int64

const (
	ComplainedEnum_NoAction   ComplainedEnum = 0
	ComplainedEnum_Complained ComplainedEnum = 1
)

type RoleEnum string

const (
	RoleEnum_User RoleEnum = "用户"
	RoleEnum_AI   RoleEnum = "AI"
)

func (r RoleEnum) String() string {
	return string(r)
}

type TableBmbAudit struct {
	ID              int64     `borm:"primary_key"`
	IsComplained    int64     `borm:"column:is_complained"`    // 用户是否申诉
	AccountID       int64     `borm:"column:account_id"`       // 用户id
	Role            int64     `borm:"column:role"`             // 角色
	QuestionTime    time.Time `borm:"column:question_time"`    // 用户提问时间
	QuestionId      string    `borm:"column:question_id"`      // 用户提问id
	QuestionContent string    `borm:"column:question_content"` // 用户提问内容
	AnswerTime      time.Time `borm:"column:answer_time"`      // AI 回答时间
	AnswerId        string    `borm:"column:answer_id"`        // AI 回答id
	AnswerContent   string    `borm:"column:answer_content"`   // 用户提问内容
	AppID           string    `borm:"column:app_id"`           // 应用id
	CreateTime      time.Time `borm:"column:create_time"`      // 创建时间
	UpdateTime      time.Time `borm:"column:update_time"`      // 更新时间
}

func (t *TableBmbAudit) TableName() string {
	return "bmb_audit"
}
