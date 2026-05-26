package impl

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

var DefaultKnowledgeBaseDocDAO *KnowledgeBaseDocDAOImpl

type KnowledgeBaseDocDAOImpl struct {
}

func newKnowledgeBaseDocDAO() *KnowledgeBaseDocDAOImpl {
	return &KnowledgeBaseDocDAOImpl{}
}

func init() {
	DefaultKnowledgeBaseDocDAO = newKnowledgeBaseDocDAO()
}

const findMaxCount = 1000

func (d *KnowledgeBaseDocDAOImpl) CreateKnowledgeBaseDoc(ctx context.Context, knowledgeBaseDoc *model.KnowledgeBaseDoc) error {
	logger := log.WithField(ctx, "CreateKnowledgeBaseDoc", knowledgeBaseDoc)
	db := mysql.AispInternalBorm

	insertResult := db.Create(ctx, knowledgeBaseDoc)
	if insertResult.Error != nil {
		logger.Errorf(ctx, "create KnowledgeBase err. err=%v", insertResult.Error)
		return insertResult.Error
	}
	return nil
}

func (d *KnowledgeBaseDocDAOImpl) FindByKnowledgeBaseId(ctx context.Context, knowledgeBaseId string) ([]*model.KnowledgeBaseDoc, error) {
	logger := log.WithField(ctx, "KnowledgeBaseId", knowledgeBaseId)
	db := mysql.AispInternalBorm

	var knowledgeBaseDocs []*model.KnowledgeBaseDoc
	err := db.Where(borm.Eq{"knowledge_base_id": knowledgeBaseId}).Where(borm.Ne{"state": model.KnowledgeBaseDocStateDeleted}).All(ctx, &knowledgeBaseDocs)
	if err != nil {
		logger.Errorf(ctx, "FindByKnowledgeBaseIde err. err=%v", err)
		return knowledgeBaseDocs, err
	}

	return knowledgeBaseDocs, nil
}

func (d *KnowledgeBaseDocDAOImpl) FindByDocId(ctx context.Context, docId string) (*model.KnowledgeBaseDoc, error) {
	logger := log.WithField(ctx, "DocId", docId)
	db := mysql.AispInternalBorm

	var knowledgeBaseDoc model.KnowledgeBaseDoc
	err := db.Where(borm.Eq{"unique_id": docId}).One(ctx, &knowledgeBaseDoc)
	if err != nil {
		logger.Errorf(ctx, "FindByDocId err. err=%v", err)
		return nil, err
	}

	return &knowledgeBaseDoc, nil
}

func (d *KnowledgeBaseDocDAOImpl) FindByDocNameAndUserId(ctx context.Context, docName string, creatorUserId string) ([]*model.KnowledgeBaseDoc, error) {
	logger := log.WithField(ctx, "DocName", docName)
	db := mysql.AispInternalBorm

	var knowledgeBaseDocs []*model.KnowledgeBaseDoc
	db = db.Where(borm.Ne{"state": model.KnowledgeBaseDocStateDeleted}).Where(borm.Eq{"creator_user_id": creatorUserId})
	if docName != "" {
		db = db.Where(borm.Like{"doc_name": "%" + docName + "%"})
	}

	err := db.Limit(findMaxCount).All(ctx, &knowledgeBaseDocs)
	if err != nil {
		logger.Errorf(ctx, "FindByDocNameAndUserId err. err=%v", err)
		return nil, err
	}

	return knowledgeBaseDocs, nil
}

func (d *KnowledgeBaseDocDAOImpl) UpdateKnowledgeBaseDoc(ctx context.Context, knowledgeBaseDoc *model.KnowledgeBaseDoc) error {
	db := mysql.AispInternalBorm

	params := map[string]interface{}{
		"unique_id": knowledgeBaseDoc.UniqueId,
	}

	if knowledgeBaseDoc.State != model.KnowledgeBaseDocStateInit {
		params["state"] = int(knowledgeBaseDoc.State)
	}

	if knowledgeBaseDoc.DocName != "" {
		params["doc_name"] = knowledgeBaseDoc.DocName
	}

	updateQueryResult := db.Model(knowledgeBaseDoc).Updates(ctx, params)
	if updateQueryResult.Error != nil {
		log.WithField(ctx, "UpdateKnowledgeBaseDoc", knowledgeBaseDoc).Errorf(ctx, "update KnowledgeBaseDoc err. err=%v", updateQueryResult.Error)
	}
	return updateQueryResult.Error
}

func (d *KnowledgeBaseDocDAOImpl) CountDocByCreatorUserId(ctx context.Context, creatorUserId string) (int64, error) {
	logger := log.WithField(ctx, "creatorUserId", creatorUserId)
	db := mysql.AispInternalBorm

	var knowledgeBase model.KnowledgeBaseDoc

	count, err := db.Where(borm.Eq{"creator_user_id": creatorUserId}).Model(&knowledgeBase).Count(ctx)
	if err != nil {
		logger.Errorf(ctx, "CountDocByCreatorUserId err. err=%v", err)
		return 0, err
	}

	return count, nil
}
