package knowledge_base

import (
	"context"
	"errors"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"github.com/google/uuid"
)

const dirPrefix = "ai-platform/knowledge_base/zhida"

func getKnowledgeBasePath(userId string, knowledgeBaseUniqueId string) string {
	return fmt.Sprintf(dirPrefix+"/%s/%s", userId, knowledgeBaseUniqueId)
}

type KnowledgeBaseService interface {
	CreateKnowLedgeBase(ctx context.Context, knowledgeBaseName string, userId string, allowExist bool) (string, error)
	UpdateKnowLedgeBase(ctx context.Context, knowledgeBase *model.KnowledgeBase) error
	FindById(ctx context.Context, uniqueId string) (*model.KnowledgeBase, error)
	FindByIdWithDocs(ctx context.Context, uniqueId string) (*model.KnowledgeBase, error)
	FindByCreatorUserId(ctx context.Context, userId string) ([]*model.KnowledgeBase, error)
}

type KnowledgebaseServiceImpl struct {
	knowledgebaseDao    dao.KnowledgeBaseDAO
	knowledgebaseDocDao dao.KnowledgeBaseDocDAO
	fileManagementDao   dao.FileManagementDAO
}

var (
	DefaultKnowledgeBaseService KnowledgeBaseService
)

func init() {
	DefaultKnowledgeBaseService = newKnowledgebaseService()
}

func newKnowledgebaseService() *KnowledgebaseServiceImpl {
	return &KnowledgebaseServiceImpl{
		knowledgebaseDao:    impl.DefaultKnowledgeBaseDAO,
		fileManagementDao:   impl.DefaultFileManagementDAO,
		knowledgebaseDocDao: impl.DefaultKnowledgeBaseDocDAO,
	}
}

func (k *KnowledgebaseServiceImpl) CreateKnowLedgeBase(ctx context.Context, knowledgeBaseName string, userId string, allowExist bool) (string, error) {
	existKnowledgeBase, err := k.knowledgebaseDao.FindByCreatorUserIdAndName(ctx, userId, knowledgeBaseName)
	if len(existKnowledgeBase) != 0 {
		if allowExist {
			return existKnowledgeBase[0].UniqueId, nil
		} else {
			return "", errors.New("已存在同名的知识库")
		}
	}

	knowledgeBaseId := uuid.New().String()
	path := getKnowledgeBasePath(userId, knowledgeBaseId)
	knowledgeBase := &model.KnowledgeBase{
		KnowledgeBaseName: knowledgeBaseName,
		CreatorUserId:     userId,
		KnowledgeBasePath: path,
		UniqueId:          knowledgeBaseId,
		State:             model.KnowledgeBaseStateInit,
	}

	_, err = k.knowledgebaseDao.CreateKnowledgeBase(ctx, knowledgeBase)
	if err != nil {
		return "", err
	}

	return knowledgeBaseId, nil
}

func (k *KnowledgebaseServiceImpl) UpdateKnowLedgeBase(ctx context.Context, knowledgeBase *model.KnowledgeBase) error {
	return k.knowledgebaseDao.UpdateKnowledgeBase(ctx, knowledgeBase)
}

func (k *KnowledgebaseServiceImpl) FindById(ctx context.Context, uniqueId string) (*model.KnowledgeBase, error) {
	knowledgeBase, err := k.knowledgebaseDao.FindById(ctx, uniqueId)
	if err != nil {
		return nil, err
	}

	return knowledgeBase, nil
}

func (k *KnowledgebaseServiceImpl) FindByIdWithDocs(ctx context.Context, uniqueId string) (*model.KnowledgeBase, error) {
	knowledgeBase, err := k.knowledgebaseDao.FindById(ctx, uniqueId)
	if err != nil {
		return nil, err
	}

	docs, err := k.knowledgebaseDocDao.FindByKnowledgeBaseId(ctx, knowledgeBase.UniqueId)
	if err != nil {
		return nil, err
	}

	knowledgeBase.Docs = docs
	return knowledgeBase, nil
}

func (k *KnowledgebaseServiceImpl) FindByCreatorUserId(ctx context.Context, userId string) ([]*model.KnowledgeBase, error) {
	return k.knowledgebaseDao.FindByCreatorUserIdAndName(ctx, userId, "")
}
