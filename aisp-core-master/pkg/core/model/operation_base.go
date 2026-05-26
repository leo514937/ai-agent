package model

import (
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
)

type StaticBase struct {
	Id                   int64     `json:"id" borm:"primary_key"`
	Scene                string    `json:"scene"`
	Question             string    `json:"question"`
	Answer               string    `json:"answer"`
	NoSymbolQuestionHash int64     `json:"no_symbol_question_hash"`
	CreateUserId         string    `json:"create_user_id"`
	UpdateUserId         string    `json:"update_user_id"`
	StatusCode           byte      `json:"status"`
	CreatedAt            time.Time `json:"created_at" borm:"readonly"` // 设置borm只读，利用数据库的能力生成 CreatedAt
	UpdatedAt            time.Time `json:"updated_at" borm:"readonly"` // 设置borm只读，利用数据库的能力更新 UpdatedAt
}

type KnowledgeBaseV2 struct {
	Id               int64     `json:"id" borm:"primary_key"`
	Scene            string    `json:"scene"`
	KeyWords         string    `json:"key_words"`
	KnowledgeContent string    `json:"knowledge_content"`
	CreateUserId     string    `json:"create_user_id"`
	UpdateUserId     string    `json:"update_user_id"`
	StatusCode       byte      `json:"status"`
	CreatedAt        time.Time `json:"created_at" borm:"readonly"` // 设置borm只读，利用数据库的能力生成 CreatedAt
	UpdatedAt        time.Time `json:"updated_at" borm:"readonly"` // 设置borm只读，利用数据库的能力更新 UpdatedAt
}

type FaqBase struct {
	Id           int64     `json:"id" borm:"primary_key"`
	Scene        string    `json:"scene"`
	Question     string    `json:"question"`
	Answer       string    `json:"answer"`
	MatchType    int       `json:"-"`
	MatchTypes   string    `json:"match_types" borm:"-"`
	CreateUserId string    `json:"create_user_id"`
	UpdateUserId string    `json:"update_user_id"`
	StatusCode   byte      `json:"status"`
	ShowRecall   byte      `json:"show_recall"`                // 是否展示召回，0:不展示，1:展示
	CreatedAt    time.Time `json:"created_at" borm:"readonly"` // 设置borm只读，利用数据库的能力生成 CreatedAt
	UpdatedAt    time.Time `json:"updated_at" borm:"readonly"` // 设置borm只读，利用数据库的能力更新 UpdatedAt
}

type LogTracing struct {
	MemberId          int64  `json:"member_id"`
	ChatScene         string `json:"chat_scene"`
	RequestMessageId  string `json:"request_message_id"`
	RequestQuery      string `json:"request_query"`
	ResponseMessageId string `json:"response_message_id"`
	ResponseAnswer    string `json:"response_answer"`
	SecurityTag       string `json:"security_tag"`
	RequestTime       string `json:"request_time"`
	RequestTimeSecond int64  `json:"request_time_second"`
	TraceId           string `json:"trace_id"`
	AppName           string `json:"app_name"`
	UnitName          string `json:"unit_name"`
	GraphName         string `json:"graph_name"`
	RequestInfo       string `json:"request_info"`
	ResponseInfo      string `json:"response_info"`
}

type LogicTracing struct {
	LogicName      string `json:"logic_name"`
	Description    string `json:"logic_description"`
	Input          string `json:"input"`
	Output         string `json:"output"`
	Process        string `json:"process"`
	StartTime      int64  `json:"start_time"`
	EndTime        int64  `json:"end_time"`
	CostMilSeconds int64  `json:"cost_mil_seconds"`
}

type Authority struct {
	Authority   int            `json:"authority"`
	Authorities map[string]int `json:"authorities"` // key是场景
}

type SceneConfig struct {
	Name         string   `json:"name"`
	AliasNames   []string `json:"alias_names"`
	RumTableName string   `json:"rum_table_name"`
}

type Scene struct {
	StaticBaseScenes   []string      `json:"static_base_scenes"`
	FaqBaseScenes      []string      `json:"faq_base_scenes"`
	FaqBaseSceneConfig []SceneConfig `json:"-"`
	TracingScenes      []string      `json:"tracing_scenes"`
}

type FilterParams struct {
	Page           int                 `json:"page,omitempty"`
	PageSize       int                 `json:"page-size,omitempty"`
	Query          string              `json:"query,omitempty"`
	Status         int                 `json:"status,omitempty"`
	CreatedAtBegin *time.Time          `json:"created-at-begin,omitempty"`
	CreatedAtEnd   *time.Time          `json:"created-at-end,omitempty"`
	CreateUserId   string              `json:"create-user-id,omitempty"`
	UpdatedAtBegin *time.Time          `json:"updated-at-begin,omitempty"`
	UpdatedAtEnd   *time.Time          `json:"updated-at-end,omitempty"`
	UpdateUserId   string              `json:"update-user-id,omitempty"`
	Scene          string              `json:"scene,omitempty"`
	MatchType      []conf.FaqMatchType `json:"match-type,omitempty"`
	MemberId       int64               `json:"member-id,omitempty"`
	MessageId      string              `json:"message-id,omitempty"`
	RespMessageId  string              `json:"resp-message-id,omitempty"`
	Security       []string            `json:"security,omitempty"`
	ChatResponse   string              `json:"chat-response,omitempty"`
	TraceId        string              `json:"trace-id,omitempty"`
	AppName        string              `json:"app-name,omitempty"`
	UnitName       string              `json:"unit-name,omitempty"`
	GraphName      string              `json:"graph-name,omitempty"`
	FeedbackSource string              `json:"feedback-source,omitempty"`
	CaseType       string              `json:"case-type,omitempty"`
	HandlingState  string              `json:"handling-state,omitempty"`
	State          int                 `json:"state,omitempty"`
	ToBeResolved   int                 `json:"to_be_resolved,omitempty"`
}

const (
	OperationBaseStatusInit = iota
	OperationBaseStatusOffline
	OperationBaseStatusOnline
	OperationBaseStatusDeleted
)

const (
	ShowRecallYes = 1
	ShowRecallNo  = 0
)
