package model

import (
	"encoding/json"
	"time"
)

type MessageType string

const (
	MessageType_Unknown   MessageType = "未知"
	MessageType_Paper_Sum MessageType = "论文摘要"
	MessageType_Paper_Qa  MessageType = "论文QA"
	MessageType_Conv      MessageType = "普通会话"
	MessageType_Vlu       MessageType = "多模态"
	MessageType_Search    MessageType = "搜索"
	MessageType_Math      MessageType = "数学"
)

type MessageTaskState string

const (
	MessageTaskState_Not_Started MessageTaskState = "未开始"
	MessageTaskState_Process     MessageTaskState = "处理中"
	MessageTaskState_End         MessageTaskState = "处理结束"
)

type MsgStopEnum string

const (
	MsgStopEnum_Pass      MsgStopEnum = "审核通过"
	MsgStopEnum_Ban       MsgStopEnum = "审核未通过"
	MsgStopEnum_Inner_Err MsgStopEnum = "内部异常"
)

type RatingEnum string

const (
	RatingEnum_No   RatingEnum = "THUMBS_NO"
	RatingEnum_Up   RatingEnum = "THUMBS_UP"   // 顶
	RatingEnum_Down RatingEnum = "THUMBS_DOWN" // 点踩
)

func (r RatingEnum) String() string {
	return string(r)
}

func (r RatingEnum) Flag() int64 {
	switch r {
	case RatingEnum_Down:
		return 2
	case RatingEnum_Up:
		return 1
	default:
		return 0
	}
}

func CreateRatingEnum(flag int64) RatingEnum {
	var rating = RatingEnum_No
	if flag == 1 {
		rating = RatingEnum_Up
	} else if flag == 2 {
		rating = RatingEnum_Down
	}
	return rating
}

type FeedbackActionEnum string

const (
	FeedbackActionEnum_Copy       FeedbackActionEnum = "COPY"
	FeedbackActionEnum_Regenerate FeedbackActionEnum = "REGENERATE" // 顶
)

func (f FeedbackActionEnum) String() string {
	return string(f)
}

type FeedBackAction struct {
	IsCopied bool `json:"is_copied"`
	IsRegen  bool `json:"is_regen"`
}

// 实现字段的自定义加载接口
// 写入数据库的时候做类型转换（`struct` -> `json string`）
func (e *FeedBackAction) Value() (interface{}, error) {
	data, err := json.Marshal(*e)
	if err != nil {
		return "", nil
	}
	return string(data), nil
}

// 加载来自数据库的类型，自动转换（`json string` -> `struct`)
func (e *FeedBackAction) SetValue(v interface{}) error {
	return json.Unmarshal(v.([]byte), &e)
}

// bmb_audit 消息审核
// bmb_conv_message 会话消息*
type TableBmbConvMessage struct {
	ID             int64          `borm:"primary_key"`
	ConvID         string         `borm:"column:conv_id"`          // 会话id
	MsgID          string         `borm:"column:msg_id"`           // 消息id
	AccountID      int64          `borm:"column:account_id"`       // 用户id
	Role           int64          `borm:"column:role"`             // 角色，1-AI，2-用户
	Content        string         `borm:"column:content"`          // 消息内容
	Rating         int64          `borm:"column:rating"`           // 评级，1-顶，2-踩
	FeedbackMsg    *string        `borm:"column:feedback_msg"`     // 反馈意见
	IsDeleted      int64          `borm:"column:is_deleted"`       // 1-未删除，2-已删除
	CreateTime     time.Time      `borm:"column:create_time"`      // 创建时间
	UpdateTime     time.Time      `borm:"column:update_time"`      // 更新时间
	FeedbackAction FeedBackAction `borm:"column:feedback_action"`  // 用户反馈动作
	ParentMsgID    string         `borm:"column:parent_msg_id"`    // 父消息ID
	CostTimeMillis int64          `borm:"column:cost_time_millis"` // 响应时间
	ImageID        *string        `borm:"column:image_id"`         // 图片ID
	MsgType        string         `borm:"column:msg_type"`         // 对话类型
	State          string         `borm:"column:state"`            // 处理状态
	StopEnum       *string        `borm:"column:stop_enum"`        // PASS安审通过，BAN安审未通过，INNER_ERR内部异常
	AppID          string         `borm:"column:app_id"`           // 应用id
	StopPosition   *int64         `borm:"column:stop_position"`    // 停止位置
}

func (t *TableBmbConvMessage) TableName() string {
	return "bmb_conv_message"
}

func (t *TableBmbConvMessage) GetColumnNames() string {
	return "id, conv_id, msg_id, account_id, role, content, rating, feedback_msg, is_deleted, create_time, update_time, feedback_action, parent_msg_id, cost_time_millis, image_id, msg_type, state, stop_enum, app_id, stop_position"
}
