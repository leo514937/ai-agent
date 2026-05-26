package service

import (
	"context"
	"errors"
	"fmt"
	"sync/atomic"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type InternalKnowledgeBaseService interface {
	CreateKnowledgeBase(ctx context.Context, params *model.KnowledgeBase) error
	DeleteKnowledgeBase(ctx context.Context, knowledgeBaseId int64) error
	GenDocId(ctx context.Context, url string) (int64, error)
	UpsertDocumentInfo(ctx context.Context, documentInfo *model.DocumentInfo) error
	GetDocumentInfo(ctx context.Context, docId int64, docType content.DocType_Type) *model.DocumentInfo
}

type InternalKnowledgeBaseServiceImpl struct {
	idGenerator        dao.IDGenerator
	knowledgebaseDao   dao.KnowledgeBaseV2Dao
	documentParsingDao dao.DocumentParsingDao
	failedCount        atomic.Int64
}

func NewInternalKnowledgeBaseServiceImpl() *InternalKnowledgeBaseServiceImpl {
	return &InternalKnowledgeBaseServiceImpl{
		idGenerator:        dao.NewIDGenerator(),
		knowledgebaseDao:   daoImpl.DefaultKnowledgeBaseV2DaoImpl,
		documentParsingDao: daoImpl.DefaultDocumentParsingDaoImpl,
	}
}

func (p *InternalKnowledgeBaseServiceImpl) CreateKnowledgeBase(ctx context.Context, params *model.KnowledgeBase) error {
	knowledgeBaseId, err := p.idGenerator.GenerateIDByType(ctx, dao.GeneratorIdTypeBaseId)
	if err != nil {
		return err
	}
	params.UniqueId = util.Int64String(knowledgeBaseId)
	return p.knowledgebaseDao.CreateKnowledgeBase(ctx, params)
}

func (p *InternalKnowledgeBaseServiceImpl) DeleteKnowledgeBase(ctx context.Context, knowledgeBaseId int64) error {
	return p.knowledgebaseDao.DeleteKnowledgeBase(ctx, knowledgeBaseId)
}

func (p *InternalKnowledgeBaseServiceImpl) UpsertDocumentInfo(ctx context.Context, documentInfo *model.DocumentInfo) error {
	// 文档 upsert
	return p.knowledgebaseDao.UpsertDocument(ctx, documentInfo)
}

func (p *InternalKnowledgeBaseServiceImpl) GenDocId(ctx context.Context, url string) (int64, error) {
	// 判断新建文档 url 是否已存在，若存在则返回错误
	if url != "" {
		existDocInfo, exist := p.knowledgebaseDao.IsDocumentUrlExist(ctx, url)
		if exist {
			return 0, errors.New(fmt.Sprintf("document url %s already exist, docId: %d", url, existDocInfo.DocId))
		}
	}
	// 生成新文档的 docId
	return p.idGenerator.GenerateIDByType(ctx, dao.GeneratorIdTypeDocumentId)
}

func (p *InternalKnowledgeBaseServiceImpl) GetDocumentInfo(ctx context.Context, docId int64, docType content.DocType_Type) *model.DocumentInfo {
	return p.knowledgebaseDao.GetDocumentInfo(ctx, docId, docType)
}
