package model

import (
	"time"
)

// badcase 列表
type BadcaseTracingList struct {
	ID                int64             `json:"id" borm:"primary_key"`
	MemberId          int64             `json:"member_id"`
	ChatScene         string            `json:"chat_scene"`
	ChatSubScene      string            `json:"chat_sub_scene"`
	RequestMessageId  string            `json:"request_message_id"`
	RequestQuery      string            `json:"request_query"`
	ResponseMessageId string            `json:"response_message_id"`
	ResponseAnswer    string            `json:"response_answer"`
	TraceId           string            `json:"trace_id"`
	FeedbackSource    string            `json:"feedback_source"`  // 反馈来源
	CaseType          string            `json:"case_type"`        // 反馈 case 类型
	CaseDescription   string            `json:"case_description"` // case 描述
	HandlingState     HandlingStateType `json:"handling_state"`   // 处理状态
	HandlingMember    string            `json:"handling_member"`  // 处理人
	HandlingResult    string            `json:"handling_result"`  // 处理结果描述
	HandlingModule    string            `json:"handling_module"`  // 处理模块
	State             int               `json:"state"`            // 有效状态，0：已删除，1：正常，2：同步中
	ToBeResolved      int               `json:"to_be_resolved"`   // 待解决，1：是待解决，0：非待解决
	FeedbackAt        time.Time         `json:"feedback_at"`      // 反馈开始时间
	CreatedAt         time.Time         `json:"created_at" borm:"readonly"`
	UpdatedAt         time.Time         `json:"updated_at" borm:"readonly"`
}

type BadcaseTracingFilterParams struct {
	Page              int
	PageSize          int
	ChatScene         []string
	MemberId          int64
	RequestMessageId  string
	RequestQuery      string
	ResponseMessageId string
	CaseType          string `json:"case_type"`
	CaseDescription   string `json:"case_description"` // case 描述
	FeedbackSource    string `json:"feedback_source"`
	HandlingState     HandlingStateType
	FeedbackStartTime *time.Time
	FeedbackEndTime   *time.Time
	RequestTime       string `json:"request_time"`
	TraceId           string `json:"trace_id"`
	State             int
	ToBeResolved      int `json:"to_be_resolved"`
}

type HandlingStateType string

const (
	NotYetHandling   HandlingStateType = "未处理"
	BeingHandling    HandlingStateType = "处理中"
	HasHandled       HandlingStateType = "已处理"
	AllHandlingState HandlingStateType = "全部"
)

// badcase 中间过程
type BadcaseTracingProcess struct {
	ID          int64     `json:"id" borm:"primary_key"`
	TraceId     string    `json:"trace_id"`
	QueryRouter string    `json:"query_router"`
	QueryMerge  string    `json:"query_merge"`
	Recalls     string    `json:"recalls"`
	Cards       string    `json:"cards"`
	Reranks     string    `json:"reranks"`
	Summary     string    `json:"summary"`
	Securities  string    `json:"securities"`
	CreatedAt   time.Time `json:"created_at" borm:"readonly"`
	UpdatedAt   time.Time `json:"updated_at" borm:"readonly"`
}
