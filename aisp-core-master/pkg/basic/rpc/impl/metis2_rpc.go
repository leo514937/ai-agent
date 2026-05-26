package impl

import (
	"context"
	"sync"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/one-rpc-go/thrift-metis2/metis2_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
)

var (
	_                    rpc.Metis2Rpc = (*Metis2RPCImpl)(nil)
	DefaultMetis2RPCImpl rpc.Metis2Rpc
)

func init() {
	DefaultMetis2RPCImpl = NewMetis2RPCImpl()
}

type Metis2RPCImpl struct {
	client *metis2_thrift.Metis2QaServiceClient
}

func NewMetis2RPCImpl() *Metis2RPCImpl {

	return &Metis2RPCImpl{
		client: metis2_thrift.NewMetis2QaServiceClient(tzone.NewClient(
			"Metis2QaService",
			tzone.TargetName("metis2-rpc"),
			tzone.Timeout(200*time.Millisecond))),
	}
}

func (m *Metis2RPCImpl) GetQuestionAnswerIds(ctx context.Context, questionId int64, topK int32) []int64 {
	var result []int64
	runFunc := func(ctx context.Context) error {
		requestParam := &metis2_thrift.GetQuestionAnswerIdsReq{
			QuestionID: questionId,
			Limit:      utils.Int32Ptr(topK),
		}
		resp, err := m.client.GetQuestionAnswerIds(ctx, requestParam)

		if err != nil || resp == nil {
			return err
		}

		result = resp.GetAnswerIds()

		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

func (m *Metis2RPCImpl) ConcurrentGetQuestionAnswerIds(ctx context.Context, questionIds []int64, topK int32, concurrency int) map[int64][]int64 {
	resultMap := sync.Map{}

	group := safe_group.NewGroupWithTimeout("ConcurrentGetQuestionAnswerIds", 500).SetLimit(concurrency)
	for _, questionId := range questionIds {
		questionId := questionId
		group.Go(func() error {
			resultMap.Store(questionId, m.GetQuestionAnswerIds(ctx, questionId, topK))
			return nil
		})
	}
	_ = group.Wait()

	result := map[int64][]int64{}
	for _, questionId := range questionIds {
		if answerIds, ok := resultMap.Load(questionId); ok {
			result[questionId] = answerIds.([]int64)
		} else {
			result[questionId] = []int64{}
		}
	}

	return result
}
