package model

import "time"

type TableBmbConvMessageProcess struct {
	ID         int64     `borm:"primary_key"`
	ConvID     string    `borm:"column:conv_id"`     // 会话id
	MsgID      string    `borm:"column:msg_id"`      // 消息id
	Tip        string    `borm:"column:tip"`         // 提示文案
	AccountID  int64     `borm:"column:account_id"`  // 用户id
	IsDeleted  int64     `borm:"column:is_deleted"`  // 1-未删除，2-已删除
	CreateTime time.Time `borm:"column:create_time"` // 创建时间
	UpdateTime time.Time `borm:"column:update_time"` // 更新时间
	AppID      string    `borm:"column:app_id"`      // 应用id
}

func (t *TableBmbConvMessageProcess) TableName() string {
	return "bmb_conv_message_process"
}
