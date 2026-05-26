package rpc

import (
	"context"
)

type QaGoRPC interface {
	// 获取用户发布回答数
	BatchGetMemberCreateAnswerCount(ctx context.Context, memberIds []int64) map[int64]int64
	GetMemberCreateAnswerIds(ctx context.Context, memberId int64, orderType OrderType, limit int64) []int64
}

type OrderType int

const (
	// 按时间排序
	OrderTypeTime OrderType = 1
	// 按热度排序
	OrderTypeHot OrderType = 2
)
