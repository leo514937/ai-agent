package rpc

import (
	"context"
)

type MemberRPC interface {
	// 获取用户关注数
	BatchGetMemberFollowingCount(ctx context.Context, memberIds []int64) map[int64]int64
	// 获取用户被关注数
	BatchGetMemberFollowerCount(ctx context.Context, memberIds []int64) map[int64]int64
}
