package model

import "time"

type SuggestionState int64

const (
	SuggestionState_Processing  SuggestionState = 0
	SuggestionState_NotAccepted SuggestionState = 1
	SuggestionState_Accepted    SuggestionState = 2
)

func (s SuggestionState) String() string {
	switch s {
	case SuggestionState_Processing:
		return "正在处理"
	case SuggestionState_NotAccepted:
		return "处理结束-未受理"
	case SuggestionState_Accepted:
		return "处理结束-已受理"
	default:
		return "unknown"
	}
}

func (s SuggestionState) Status() int64 {
	return int64(s)
}

// bmb_suggestion 反馈建议*
type TableBmbSuggestion struct {
	ID           int64      `borm:"primary_key"`
	Status       int64      `borm:"column:status"`        // 状态 0 - 正在处理，1 -处理结束-未受理，2- 处理结束-已受理,  ',
	Numbered     string     `borm:"column:numbered"`      // 编号
	Content      string     `borm:"column:content"`       // 反馈内容
	AuditContent string     `borm:"column:audit_content"` // 审核意见
	AccountID    int64      `borm:"column:account_id"`    // 用户id
	AppID        string     `borm:"column:app_id"`        // 渠道
	CreateTime   time.Time  `borm:"column:create_time"`   // 创建时间
	AuditTime    *time.Time `borm:"column:audit_time"`    // 审核时间
	UpdateTime   time.Time  `borm:"column:update_time"`   // 更新时间
}

func (t *TableBmbSuggestion) TableName() string {
	return "bmb_suggestion"
}

func (t *TableBmbSuggestion) GetColumnNames() string {
	return "id, status, numbered, content, audit_content, account_id, app_id, create_time, audit_time, update_time"
}
