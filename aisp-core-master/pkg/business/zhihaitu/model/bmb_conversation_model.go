package model

import "time"

// bmb_conv_message_process 会话消息处理
// bmb_conversation 会话*
type TableBmbConversation struct {
	ID           int64     `borm:"primary_key"`
	ConvID       string    `borm:"column:conv_id"`        // 会话id
	AccountID    int64     `borm:"column:account_id"`     // 用户id
	Title        string    `borm:"column:title"`          // 会话标题
	IsDeleted    int64     `borm:"column:is_deleted"`     // 1-未删除，2-已删除
	CreateTime   time.Time `borm:"column:create_time"`    // 创建时间
	UpdateTime   time.Time `borm:"column:update_time"`    // 更新时间
	LatexPaperID *string   `borm:"column:latex_paper_id"` // 论文ID
	ImageID      *string   `borm:"column:image_id"`       // 图片ID
	AppID        string    `borm:"column:app_id"`         // 应用id
	DisposeState int64     `borm:"column:dispose_state"`  // 处置状态
}

func (t *TableBmbConversation) TableName() string {
	return "bmb_conversation"
}
