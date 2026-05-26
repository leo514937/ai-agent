package impl

import (
	"context"

	"git.in.zhihu.com/go/borm"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type KnowledgeBaseV2DaoImpl struct {
	db *borm.ORM
}

var _ dao.KnowledgeBaseV2Dao = (*KnowledgeBaseV2DaoImpl)(nil)

var DefaultKnowledgeBaseV2DaoImpl *KnowledgeBaseV2DaoImpl

func init() {
	DefaultKnowledgeBaseV2DaoImpl = NewKnowledgeBaseV2DaoImpl()
}

func NewKnowledgeBaseV2DaoImpl() *KnowledgeBaseV2DaoImpl {
	return &KnowledgeBaseV2DaoImpl{
		db: mysql.AispInternalBorm,
	}
}

func (d *KnowledgeBaseV2DaoImpl) CreateKnowledgeBase(ctx context.Context, knowledgeBase *model.KnowledgeBase) error {
	logger := log.WithField(ctx, "knowledgeBase", knowledgeBase)
	db := d.db

	insertResult := db.Create(ctx, knowledgeBase)
	if insertResult.Error != nil {
		logger.Errorf(ctx, "CreateKnowledgeBase err. err=%v", insertResult.Error)
		return insertResult.Error
	}
	return nil
}

func (d *KnowledgeBaseV2DaoImpl) DeleteKnowledgeBase(ctx context.Context, knowledgeBaseId int64) error {
	logger := log.WithField(ctx, "knowledgeBaseId", knowledgeBaseId)
	db := d.db

	updateResult := db.Model(&model.KnowledgeBase{}).Where(borm.Eq{"unique_id": util.Int64String(knowledgeBaseId)}).UpdateRaw(ctx, map[string]interface{}{
		"state": model.KnowledgeBaseStateDeleted,
	})
	if updateResult.Error != nil {
		logger.Errorf(ctx, "DeleteKnowledgeBase err. err=%v", updateResult.Error)
		return updateResult.Error
	}
	return nil
}

func (d *KnowledgeBaseV2DaoImpl) IsDocumentUrlExist(ctx context.Context, url string) (*model.DocumentInfo, bool) {
	logger := log.WithField(ctx, "url", url)
	db := d.db

	var documentInfo model.DocumentInfo
	err := db.Where(borm.Eq{"url": url}).One(ctx, &documentInfo)
	if err != nil {
		logger.Infof(ctx, "Document is not exist. err=%v", err)
		return nil, false
	}
	return &documentInfo, documentInfo.DocId != 0
}

func (d *KnowledgeBaseV2DaoImpl) IsDocumentIdExist(ctx context.Context, docId int64, docType string) (int64, bool) {
	logger := log.WithField(ctx, "docId", docId)
	db := d.db

	var documentInfo model.DocumentInfo
	err := db.Where(borm.Eq{"doc_id": docId, "doc_type": docType}).One(ctx, &documentInfo)
	if err != nil {
		logger.Infof(ctx, "Document is not exist. err=%v", err)
		return 0, false
	}
	return documentInfo.Id, documentInfo.DocId != 0
}

func (d *KnowledgeBaseV2DaoImpl) UpsertDocument(ctx context.Context, documentInfo *model.DocumentInfo) error {
	logger := log.WithField(ctx, "documentInfo", documentInfo)
	db := d.db

	id, exist := d.IsDocumentIdExist(ctx, documentInfo.DocId, documentInfo.DocType)
	if exist {
		params := map[string]interface{}{
			"id":                id,
			"title":             documentInfo.Title,
			"abstract":          documentInfo.Abstract,
			"content":           documentInfo.Content,
			"last_updated_time": documentInfo.LastUpdatedTime,
			"url":               documentInfo.Url,
			"tags":              documentInfo.Tags,
			"authority_level":   documentInfo.AuthorityLevel,
			"doc_source":        documentInfo.DocSource,
			"operator":          documentInfo.Operator,
		}
		updateResult := db.Model(documentInfo).Updates(ctx, params)
		if updateResult.Error != nil {
			logger.Errorf(ctx, "UpdateDocument err. err=%v", updateResult.Error)
			return updateResult.Error
		}
	} else {
		insertResult := db.Create(ctx, documentInfo)
		if insertResult.Error != nil {
			logger.Errorf(ctx, "InsertDocument err. err=%v", insertResult.Error)
			return insertResult.Error
		}
	}
	return nil
}

func (d *KnowledgeBaseV2DaoImpl) GetDocumentInfo(ctx context.Context, docId int64, docType content.DocType_Type) *model.DocumentInfo {
	logger := log.WithField(ctx, "docId", docId)
	db := d.db

	var documentInfo model.DocumentInfo
	err := db.Where(borm.Eq{"doc_id": docId, "doc_type": docType.String()}).One(ctx, &documentInfo)
	if err != nil {
		logger.Errorf(ctx, "GetDocumentInfo err. err=%v", err)
		return nil
	}
	return &documentInfo
}

func (d *KnowledgeBaseV2DaoImpl) DeleteDocument(ctx context.Context, docId int64, docType string) error {
	logger := log.WithField(ctx, "docId", docId)
	db := d.db

	result := db.Model(&model.DocumentInfo{}).Where(borm.Eq{"doc_id": docId, "doc_type": docType}).DeleteRaw(ctx)
	if result.Error != nil {
		logger.Errorf(ctx, "DeleteDocument err. err=%v", result.Error)
		return result.Error
	}
	return nil
}

func (d *KnowledgeBaseV2DaoImpl) AddKnowledgeBaseDocument(ctx context.Context, knowledgeBaseDoc *model.KnowledgeBaseDocV2) error {
	logger := log.WithField(ctx, "knowledgeBaseDoc", knowledgeBaseDoc)
	db := d.db

	insertResult := db.Create(ctx, knowledgeBaseDoc)
	if insertResult.Error != nil {
		logger.Errorf(ctx, "AddKnowledgeBaseDocument err. err=%v", insertResult.Error)
		return insertResult.Error
	}
	return nil
}

func (d *KnowledgeBaseV2DaoImpl) DeleteKnowledgeBaseDocument(ctx context.Context, knowledgeBaseDoc *model.KnowledgeBaseDocV2) error {
	logger := log.WithField(ctx, "knowledgeBaseDoc", knowledgeBaseDoc)
	db := d.db

	result := db.Model(knowledgeBaseDoc).Where(borm.Eq{
		"knowledge_base_id":   knowledgeBaseDoc.KnowledgeBaseId,
		"knowledge_base_type": knowledgeBaseDoc.KnowledgeBaseType,
		"doc_id":              knowledgeBaseDoc.DocId,
		"doc_type":            knowledgeBaseDoc.DocType,
	}).DeleteRaw(ctx)
	if result.Error != nil {
		logger.Errorf(ctx, "DeleteKnowledgeBaseDocument err. err=%v", result.Error)
		return result.Error
	}
	return nil
}

func (d *KnowledgeBaseV2DaoImpl) GetKnowledgeBaseDocument(ctx context.Context, knowledgeBaseId int64, knowledgeBaseType proto.PersonalKnowledgeBaseType) ([]*model.KnowledgeBaseDocV2, error) {
	logger := log.WithField(ctx, "knowledgeBaseId", knowledgeBaseId)
	db := d.db

	var knowledgeBaseDocs []*model.KnowledgeBaseDocV2
	err := db.Where(borm.Eq{"knowledge_base_id": knowledgeBaseId, "knowledge_base_type": knowledgeBaseType}).All(ctx, &knowledgeBaseDocs)
	if err != nil {
		logger.Errorf(ctx, "GetKnowledgeBaseDocument err. err=%v", err)
		return nil, err
	}
	return knowledgeBaseDocs, nil
}
