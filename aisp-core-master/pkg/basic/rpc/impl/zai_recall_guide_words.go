package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/pb-go/zai-proto/ai/user_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

var (
	_ rpc.ZaiRecallGuideWordGRPC = (*ZaiRecallGuideWordGRPCImpl)(nil)
)

type ZaiRecallGuideWordGRPCImpl struct {
	timeout   time.Duration
	zaiClient user_grpc.UserGuideWordsServiceClient
}

func NewZaiRecallGuideWordGRPCImpl() *ZaiRecallGuideWordGRPCImpl {
	zaiClientContext, err := grpc.DialContext(context.Background(), "zai-user-guide-words")
	if err != nil {
		log.Errorf(context.Background(), "dial zai-user-guide-words err: %+v", err)

		panic(err)
	}

	return &ZaiRecallGuideWordGRPCImpl{
		zaiClient: user_grpc.NewUserGuideWordsServiceClient(zaiClientContext),
		timeout:   1500 * time.Millisecond,
	}
}

func (z ZaiRecallGuideWordGRPCImpl) RecallGuideWords(ctx context.Context, request *user_grpc.UserGuideWordsRequest) *user_grpc.UserGuideWordsResponse {
	var resp *user_grpc.UserGuideWordsResponse
	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, z.timeout)
		defer cancel()

		res, err := z.zaiClient.Recall(newCtx, request)
		if err != nil {
			return err
		}
		resp = res
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return resp
}
