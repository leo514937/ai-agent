package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/thrift-go/member_thrift/relation"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
)

type MemberRPCImpl struct {
	relationClient *relation.RelationServiceClient
}

var DefaultMemberRPCImpl rpc.MemberRPC

func init() {
	DefaultMemberRPCImpl = NewMemberRPCImpl()
}
func NewMemberRPCImpl() *MemberRPCImpl {
	return &MemberRPCImpl{
		relationClient: relation.NewRelationServiceClient(tzone.NewClient(
			"RelationService",
			tzone.Timeout(300*time.Millisecond),
			tzone.TargetName("member"))),
	}
}

func (r *MemberRPCImpl) BatchGetMemberFollowingCount(ctx context.Context, memberIds []int64) map[int64]int64 {
	var res = make(map[int64]int64)
	runFunc := func(ctx context.Context) (err error) {
		resp, err := r.relationClient.MGetFollowingNum(ctx, memberIds)
		if err == nil && len(memberIds) == len(resp) {
			for i, followingCnt := range resp {
				res[memberIds[i]] = followingCnt
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func (r *MemberRPCImpl) BatchGetMemberFollowerCount(ctx context.Context, memberIds []int64) map[int64]int64 {
	var res = make(map[int64]int64)
	runFunc := func(ctx context.Context) (err error) {
		resp, err := r.relationClient.MGetFollowerNum(ctx, memberIds)
		if err == nil && len(memberIds) == len(resp) {
			for i, followerCnt := range resp {
				res[memberIds[i]] = followerCnt
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

var _ rpc.MemberRPC = (*MemberRPCImpl)(nil)
