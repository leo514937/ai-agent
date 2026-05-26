package rpc

import "context"

type KlaraRpcClient interface {
	// BatchInferEmbedding 计算 embedding
	BatchInferEmbedding(ctx context.Context, texts []string) [][]float32

	BatchInferEmbeddingBySize(ctx context.Context, texts []string, batchSize int) [][]float32

	// BatchInferPairwiseScore 计算 pairwise score
	BatchInferPairwiseScore(ctx context.Context, textsSlice [][]string) []float32

	BatchInferPairwiseScoreBySize(ctx context.Context, textsSlice [][]string, batchSize int) []float32
	BatchInferPairwiseEmbeddingBySize(ctx context.Context, contentSlice [][]string, batchSize int) [][]float32

	BatchInferBgeM3DenseEmb(ctx context.Context, contentSlice []string) [][]float32
	BatchInferBgeM3Sparse(ctx context.Context, contentSlice []string) [][]SegWord
}

type SegWord struct {
	Id     int64
	Word   string
	Weight float32
}
