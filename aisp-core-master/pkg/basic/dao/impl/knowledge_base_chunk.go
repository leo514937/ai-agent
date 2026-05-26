package impl

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

var DefaultKnowledgeBaseChunkDAO dao.KnowledgeBaseChunkDAO

type KnowledgeBaseChunkDAOImpl struct {
}

func NewKnowledgeBaseChunkDAOImpl() *KnowledgeBaseChunkDAOImpl {
	return &KnowledgeBaseChunkDAOImpl{}
}

func init() {
	DefaultKnowledgeBaseChunkDAO = NewKnowledgeBaseChunkDAOImpl()
}

func (k *KnowledgeBaseChunkDAOImpl) CreateKnowledgeBaseChunk(ctx context.Context, knowledgeBaseChunk *model.KnowledgeBaseChunk) error {
	logger := log.WithField(ctx, "CreateKnowledgeBaseChunk", knowledgeBaseChunk)
	db := mysql.AispInternalBorm

	insertResult := db.Create(ctx, knowledgeBaseChunk)
	if insertResult.Error != nil {
		logger.Errorf(ctx, "create knowledgeBaseChunk err. err=%v", insertResult.Error)
		return insertResult.Error
	}
	return nil
}

func (k *KnowledgeBaseChunkDAOImpl) DeleteKnowledgeBaseChunk(ctx context.Context, chunk *model.KnowledgeBaseChunk) error {
	db := mysql.AispInternalBorm

	err := db.Delete(ctx, chunk)
	if err != nil {
		log.WithField(ctx, "DeleteKnowledgeBaseChunk", chunk).Errorf(ctx, "DeleteKnowledgeBaseChunk err. err=%v", err)
	}

	return err
}

func (k *KnowledgeBaseChunkDAOImpl) FindByDocId(ctx context.Context, docId string) ([]*model.KnowledgeBaseChunk, error) {
	logger := log.WithField(ctx, "KnowledgeBaseChunkId", docId)
	db := mysql.AispInternalBorm

	var knowledgeBaseChunks []*model.KnowledgeBaseChunk
	err := db.Where(borm.Eq{"doc_id": docId}).All(ctx, &knowledgeBaseChunks)
	if err != nil {
		logger.Errorf(ctx, "FindByDocId err. err=%v", err)
		return knowledgeBaseChunks, err
	}

	return knowledgeBaseChunks, nil
}
