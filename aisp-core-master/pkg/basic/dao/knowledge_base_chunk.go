package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type KnowledgeBaseChunkDAO interface {
	CreateKnowledgeBaseChunk(ctx context.Context, knowledgeBaseChunk *model.KnowledgeBaseChunk) error
	DeleteKnowledgeBaseChunk(ctx context.Context, chunk *model.KnowledgeBaseChunk) error
	FindByDocId(ctx context.Context, docId string) ([]*model.KnowledgeBaseChunk, error)
}
