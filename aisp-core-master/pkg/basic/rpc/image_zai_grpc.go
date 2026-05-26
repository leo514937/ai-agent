package rpc

import (
	"context"
)

type ImageZaiGrpc interface {
	ConcurrentIsImagePlanText(ctx context.Context, imageTokens []string, concurrency int) map[string]bool
	ConcurrentIsImageVulgar(ctx context.Context, imageTokens []string, concurrency int) map[string]bool
	ConcurrentGetTextEmbedding(ctx context.Context, texts []string, concurrency int) [][]float32
	ConcurrentGetImageEmbedding(ctx context.Context, imageTokens []string, concurrency int) map[string][]float32
}
