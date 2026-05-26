package rpc

import (
	"context"
)

type ArticleRPC interface {
	// 获取用户发布文章数
	BatchGetMemberCreateArticleCount(ctx context.Context, memberIds []int64) map[int64]int64
	GetMemberCreateArticleIds(ctx context.Context, memberId int64, orderType OrderType, limit int64) []int64
}
