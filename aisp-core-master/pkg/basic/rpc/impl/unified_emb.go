package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/pb-go/zai-proto/ai/common"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type UnifiedEmbGrpcImpl struct {
	timeout time.Duration
	client  content_grpc.UnifiedEmbeddingServiceClient
}

var DefaultUnifiedEmbGrpcImpl rpc.UnifiedEmbGRPC

func init() {
	DefaultUnifiedEmbGrpcImpl = NewUnifiedEmbImpl()
}

func NewUnifiedEmbImpl() *UnifiedEmbGrpcImpl {
	conn, err := grpc.DialContext(context.Background(), "unified-embedding")
	if err != nil {
		log.Errorf(context.Background(), "dial unified-embedding err: %+v", err)

		panic(err)
	}

	return &UnifiedEmbGrpcImpl{
		client:  content_grpc.NewUnifiedEmbeddingServiceClient(conn),
		timeout: 1000 * time.Millisecond,
	}
}

func NewUnifiedEmbImplForSearch() *UnifiedEmbGrpcImpl {
	conn, err := grpc.DialContext(context.Background(), "unified-embedding-search")
	if err != nil {
		log.Errorf(context.Background(), "dial unified-embedding err: %+v", err)

		panic(err)
	}

	return &UnifiedEmbGrpcImpl{
		client:  content_grpc.NewUnifiedEmbeddingServiceClient(conn),
		timeout: 1000 * time.Millisecond,
	}
}

func (u *UnifiedEmbGrpcImpl) GetEmbedding(ctx context.Context, text string, embeddingType common.EmbeddingType_Type) []float32 {
	var result []float32
	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, u.timeout)
		defer cancel()

		request := &content_grpc.UnifiedEmbeddingRequest{
			DocType:       content.DocType_Text,
			EmbeddingType: embeddingType,
			Text:          text,
		}

		response, err := u.client.Embedding(newCtx, request)

		if err == nil && response != nil {
			result = response.GetEmbedding()
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

func (u *UnifiedEmbGrpcImpl) BatchGetTextKlaraEmbedding(ctx context.Context, texts []string, embeddingType common.EmbeddingType_Type) [][]float32 {
	var result [][]float32
	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, u.timeout)
		defer cancel()

		request := &content_grpc.BatchUnifiedEmbeddingKlaraRequest{
			DocType:       content.DocType_Text,
			EmbeddingType: embeddingType,
			Text:          texts,
		}

		response, err := u.client.BatchKlaraEmbedding(newCtx, request)

		if err == nil && response != nil {
			for _, each := range response.GetEmbeddingResponse() {
				result = append(result, each.GetEmbedding())
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

var _ rpc.UnifiedEmbGRPC = (*UnifiedEmbGrpcImpl)(nil)
