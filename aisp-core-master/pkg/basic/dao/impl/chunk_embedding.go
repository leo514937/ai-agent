package impl

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
)

type ChunkEmbeddingDaoImpl struct {
	redisClient redis.Client
}

var _ dao.ChunkEmbeddingDao = (*ChunkEmbeddingDaoImpl)(nil)

var DefaultChunkEmbeddingDaoImpl *ChunkEmbeddingDaoImpl

func init() {
	DefaultChunkEmbeddingDaoImpl = NewChunkEmbeddingDaoImpl()
}

func NewChunkEmbeddingDaoImpl() *ChunkEmbeddingDaoImpl {
	return &ChunkEmbeddingDaoImpl{
		redisClient: resource.RedisByChunkEmbedding,
	}
}

func (c ChunkEmbeddingDaoImpl) GetChunkEmbedding(ctx context.Context, docId int64, docType content.DocType_Type) map[string]float32 {
	//TODO implement me
	panic("implement me")
}

func (c ChunkEmbeddingDaoImpl) SetChunkEmbedding(ctx context.Context, docId int64, docType content.DocType_Type) (bool, error) {
	//TODO implement me
	panic("implement me")
}

func (c ChunkEmbeddingDaoImpl) ExistChunkEmbedding(ctx context.Context, docId int64, docType content.DocType_Type) (bool, error) {
	//TODO implement me
	panic("implement me")
}
