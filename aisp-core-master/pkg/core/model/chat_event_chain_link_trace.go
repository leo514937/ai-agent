package model

import "time"

type ChatEventChainLinkTrace struct {
	ID                 int64     `json:"id" borm:"primary_key"`
	TraceId            string    `json:"trace_id"`
	ChainLinkTraceJson string    `json:"chain_link_trace_json" borm:""` //
	MiddleProcess      string    `json:"middle_process" borm:""`        //
	CreatedAt          time.Time `json:"created_at" borm:"readonly"`    // 创建时间 设置borm只读，利用数据库的能力生成 CreatedAt
	UpdatedAt          time.Time `json:"updated_at" borm:"readonly"`    // 修改时间 设置borm只读，利用数据库的能力生成 CreatedAt
}
