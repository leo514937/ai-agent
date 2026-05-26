package rpc

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/common"
)

type UnifiedEmbGRPC interface {
	BatchGetTextKlaraEmbedding(ctx context.Context, texts []string, embeddingType common.EmbeddingType_Type) [][]float32
	GetEmbedding(ctx context.Context, text string, embeddingType common.EmbeddingType_Type) []float32
}
