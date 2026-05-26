package rpc

import (
	"context"
)

type MemberProfileRPC interface {
	// 获取用户获得的赞同数
	BatchGetMemberRecievedVoteup(ctx context.Context, memberIds []int64) map[int64]int64
}
