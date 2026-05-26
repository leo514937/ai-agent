package model

import "time"

type ReportState string

const (
	ReportState_Process      ReportState = "正在处理"
	ReportState_Accepted     ReportState = "处理结束·已受理"
	ReportState_Not_Accepted ReportState = "处理结束·未受理"
)

func (r ReportState) String() string {
	return string(r)
}

// report_msg 消息反馈*
type TableReportMsg struct {
	ID           int64     `borm:"primary_key"`
	AccountID    int64     `borm:"column:account_id"`    // 用户id
	ConvID       string    `borm:"column:conv_id"`       // 会话id
	MsgID        string    `borm:"column:msg_id"`        // 消息id
	ReportNo     string    `borm:"column:report_no"`     // 反馈编号
	AIContent    string    `borm:"column:ai_content"`    // 消息内容
	ReportReason string    `borm:"column:report_reason"` // 反馈理由
	ReportState  string    `borm:"column:report_state"`  // 反馈状态
	CreateTime   time.Time `borm:"column:create_time"`   // 创建时间
	UpdateTime   time.Time `borm:"column:update_time"`   // 更新时间
}

func (t *TableReportMsg) TableName() string {
	return "report_msg"
}

func (t *TableReportMsg) GetColumnNames() string {
	return "id, account_id, conv_id, msg_id, report_no, ai_content, report_reason, report_state, create_time, update_time"
}
