package rpc

import (
	"context"

	searchThrift "git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type SearchHit = searchThrift.SearchHit

type SearchServiceRequest struct {
	Query              string
	Offset             int32
	Limit              int32
	TimeAfter          int32
	TimeBefore         int32
	Vertical           []searchThrift.Vertical
	RestrictedScope    *searchThrift.RestrictedScope
	SearchFilterOption *searchThrift.SearchFilterOption
	// MemberID 用户ID 可空（目前主要用于实验）
	MemberID int64
	// AbParams Ab 实验参数 K,V K=实验Key V=实验结果
	AbParams map[string]string
	// NeedQueryCorrection 是否需要query 校正
	NeedQueryCorrection bool
}

type OutSiteSearchRecallAnswerResult struct {
	Url           string
	Name          string
	Snippet       string
	Summary       string
	MainText      string
	PublishedTime int64 // 发布时间, 秒级时间戳
	ExtraInfo     *model.ExtraInfo
}

type SearchServiceRPC interface {
	Search(ctx context.Context, request SearchServiceRequest) []*SearchHit
	RealTimeSearch(ctx context.Context, request SearchServiceRequest) []*SearchHit
}
