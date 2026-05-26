package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type KnowledgeBaseDAO interface {
	CreateKnowledgeBase(ctx context.Context, KnowledgeBase *model.KnowledgeBase) (int64, error)
	UpdateKnowledgeBase(ctx context.Context, knowledgeBase *model.KnowledgeBase) error
	FindById(ctx context.Context, id string) (*model.KnowledgeBase, error)
	FindByCreatorUserIdAndName(ctx context.Context, creatorUserId string, knowledgeBaseName string) ([]*model.KnowledgeBase, error)
}
