package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type KnowledgeBaseDocDAO interface {
	CreateKnowledgeBaseDoc(ctx context.Context, knowledgeBaseDoc *model.KnowledgeBaseDoc) error
	UpdateKnowledgeBaseDoc(ctx context.Context, knowledgeBase *model.KnowledgeBaseDoc) error
	FindByKnowledgeBaseId(ctx context.Context, knowledgeBaseId string) ([]*model.KnowledgeBaseDoc, error)
	FindByDocId(ctx context.Context, docId string) (*model.KnowledgeBaseDoc, error)
	FindByDocNameAndUserId(ctx context.Context, docName string, creatorUserId string) ([]*model.KnowledgeBaseDoc, error)
	CountDocByCreatorUserId(ctx context.Context, creatorUserId string) (int64, error)
}
