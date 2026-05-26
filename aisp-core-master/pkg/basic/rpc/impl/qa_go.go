package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	qAGoMember "git.in.zhihu.com/thrift-go/qa_go_thrift/member"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
)

type QaGoRPCImpl struct {
	qaMemberClient *qAGoMember.MemberServiceClient
}

var DefaultQaGoRPCImpl rpc.QaGoRPC

func init() {
	DefaultQaGoRPCImpl = NewQaGoRPCImpl()
}
func NewQaGoRPCImpl() *QaGoRPCImpl {
	return &QaGoRPCImpl{
		qaMemberClient: qAGoMember.NewMemberServiceClient(tzone.NewClient(
			"MemberService",
			tzone.TargetName("qa-go-rpc"),
			tzone.Timeout(200*time.Millisecond),
		)),
	}
}

func (r *QaGoRPCImpl) BatchGetMemberCreateAnswerCount(ctx context.Context, memberIds []int64) map[int64]int64 {
	var res = make(map[int64]int64)
	runFunc := func(ctx context.Context) (err error) {
		param := &qAGoMember.BatchGetStatisticsParam{
			MemberIds: memberIds,
			WithFields: &[]qAGoMember.StatisticsField{
				qAGoMember.StatisticsField_DISPLAY_ANSWER_COUNT,
			},
		}

		resp, err := r.qaMemberClient.BatchGetStatistics(ctx, param)
		if err == nil && resp != nil {
			for memberId, statistics := range resp {
				res[memberId] = statistics.GetDisplayAnswerCount()
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

func (r *QaGoRPCImpl) GetMemberCreateAnswerIds(ctx context.Context, memberId int64, orderType rpc.OrderType, limit int64) []int64 {
	var res = make([]int64, 0)
	runFunc := func(ctx context.Context) (err error) {
		var resp []int64
		if orderType == rpc.OrderTypeHot {
			param := &qAGoMember.GetMemberAnswerIdsByVoteNumParam{
				MemberID: &memberId,
				Limit:    &limit,
			}
			resp, err = r.qaMemberClient.GetMemberAnswerIdsByVoteNum(ctx, param)
		} else if orderType == rpc.OrderTypeTime {
			param := &qAGoMember.GetMemberAnswerIdsByCreatedParam{
				MemberID: &memberId,
				Limit:    &limit,
			}
			resp, err = r.qaMemberClient.GetMemberAnswerIdsByCreated(ctx, param)
		}

		if err == nil && resp != nil {
			res = resp
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return res
}

var _ rpc.QaGoRPC = (*QaGoRPCImpl)(nil)
