package impl

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

var DefaultKnowledgeBaseDAO dao.KnowledgeBaseDAO

type KnowledgeBaseDAOImpl struct {
}

func NewKnowledgeBaseDAO() *KnowledgeBaseDAOImpl {
	return &KnowledgeBaseDAOImpl{}
}

func init() {
	DefaultKnowledgeBaseDAO = NewKnowledgeBaseDAO()
}

func (d *KnowledgeBaseDAOImpl) CreateKnowledgeBase(ctx context.Context, knowledgeBase *model.KnowledgeBase) (int64, error) {
	logger := log.WithField(ctx, "knowledgeBase", knowledgeBase)
	db := mysql.AispInternalBorm

	insertResult := db.Create(ctx, knowledgeBase)
	if insertResult.Error != nil {
		logger.Errorf(ctx, "create KnowledgeBase err. err=%v", insertResult.Error)
		return -1, insertResult.Error
	}
	return insertResult.LastInsertedID, nil

}

func (d *KnowledgeBaseDAOImpl) UpdateKnowledgeBase(ctx context.Context, knowledgeBase *model.KnowledgeBase) error {
	db := mysql.AispInternalBorm

	params := map[string]interface{}{
		"unique_id": knowledgeBase.UniqueId,
		"state":     knowledgeBase.State,
	}

	if knowledgeBase.KnowledgeBaseName != "" {
		params["knowledge_base_name"] = knowledgeBase.KnowledgeBaseName
	}

	updateQueryResult := db.Model(&knowledgeBase).Updates(ctx, params)
	err := updateQueryResult.Error
	if err != nil {
		log.WithField(ctx, "knowledgeBase", knowledgeBase).Errorf(ctx, "update KnowledgeBase err. err=%v", err)
	}
	return err
}

func (d *KnowledgeBaseDAOImpl) FindById(ctx context.Context, id string) (*model.KnowledgeBase, error) {
	db := mysql.AispInternalBorm

	knowledgeBase := &model.KnowledgeBase{}
	err := db.Where(borm.Eq{"unique_id": id}).Where(borm.Eq{"state": model.KnowledgeBaseStateInit}).One(ctx, knowledgeBase)
	if err != nil {
		log.WithField(ctx, "knowledgeBase", knowledgeBase).Errorf(ctx, "find KnowledgeBase err. err=%v", err)
		return nil, err
	}

	return knowledgeBase, nil
}

func (d *KnowledgeBaseDAOImpl) FindByCreatorUserIdAndName(ctx context.Context, creatorUserId string, name string) ([]*model.KnowledgeBase, error) {
	db := mysql.AispInternalBorm

	var knowledgeBases []*model.KnowledgeBase
	db = db.Where(borm.Eq{"creator_user_id": creatorUserId}).Where(borm.Eq{"state": model.KnowledgeBaseStateInit})
	if name != "" {
		db = db.Where(borm.Eq{"knowledge_base_name": name})
	}

	err := db.All(ctx, &knowledgeBases)
	if err != nil {
		log.WithField(ctx, "creatorUserId", creatorUserId).Errorf(ctx, "FindByCreatorUserIdAndName err. err=%v", err)
		return nil, err
	}

	return knowledgeBases, nil
}
