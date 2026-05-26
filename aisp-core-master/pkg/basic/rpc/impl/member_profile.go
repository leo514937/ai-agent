package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	profiled_thrift "git.in.zhihu.com/thrift-go/profiled_thrift/member"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
)

type MemberProfileRPCImpl struct {
	memberServiceClient *profiled_thrift.MemberServiceClient
}

var DefaultMemberProfileRPCImpl rpc.MemberProfileRPC

func init() {
	DefaultMemberProfileRPCImpl = NewMemberProfileRpcImpl()
}
func NewMemberProfileRpcImpl() *MemberProfileRPCImpl {
	return &MemberProfileRPCImpl{
		memberServiceClient: profiled_thrift.NewMemberServiceClient(tzone.NewClient(
			"MemberService",
			tzone.TargetName("profile-service-go"),
			tzone.Timeout(300*time.Millisecond),
		)),
	}
}

func (r *MemberProfileRPCImpl) BatchGetMemberRecievedVoteup(ctx context.Context, memberIds []int64) map[int64]int64 {
	var res = make(map[int64]int64)
	runFunc := func(ctx context.Context) (err error) {
		param := &profiled_thrift.BatchGetStatisticsParam{
			MemberIds: memberIds,
			WithFields: []profiled_thrift.StatisticsField{
				profiled_thrift.StatisticsField_TOTAL_VOTEUP_COUNT,
			},
		}

		resp, err := r.memberServiceClient.MgetStatistics(ctx, param)
		if err == nil && resp != nil {
			for memberId, statistics := range resp {
				res[memberId] = statistics.GetTotalVoteupCount()
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

var _ rpc.MemberProfileRPC = (*MemberProfileRPCImpl)(nil)
