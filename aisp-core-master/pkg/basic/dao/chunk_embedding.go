package dao

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

type ChunkEmbeddingDao interface {
	GetChunkEmbedding(ctx context.Context, docId int64, docType content.DocType_Type) map[string]float32
	SetChunkEmbedding(ctx context.Context, docId int64, docType content.DocType_Type) (bool, error)
	ExistChunkEmbedding(ctx context.Context, docId int64, docType content.DocType_Type) (bool, error)
}
