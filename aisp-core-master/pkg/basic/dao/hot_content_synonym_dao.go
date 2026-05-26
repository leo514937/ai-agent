package dao

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type HotContentSynonymDAO interface {
	AddSynonyms(ctx context.Context, synonyms []*model.HotContentProductSynonym) error
	UpdateSynonym(ctx context.Context, synonym *model.HotContentProductSynonym) error
	ListSynonyms(ctx context.Context, filterParams *model.HotContentSynonymFilterParams) ([]*model.HotContentProductSynonym, error)
	GetTotalCount(ctx context.Context, filterParams *model.HotContentSynonymFilterParams) (int64, error)
}

type HotContentSynonymDAOImpl struct {
}

var DefaultHotContentSynonymDAO HotContentSynonymDAO = NewHotContentSynonymDAOImpl()

func NewHotContentSynonymDAOImpl() *HotContentSynonymDAOImpl {
	return &HotContentSynonymDAOImpl{}
}

func (h *HotContentSynonymDAOImpl) AddSynonyms(ctx context.Context, synonyms []*model.HotContentProductSynonym) error {
	db := mysql.AispInternalBorm

	insertResult := db.CreateMany(ctx, synonyms)
	if insertResult.Error != nil {
		log.WithField(ctx, "AddSynonyms", synonyms).Errorf(ctx, "add HotContentProductSynonym err. err=%v", insertResult.Error)
		return insertResult.Error
	}

	return nil
}

func (h *HotContentSynonymDAOImpl) UpdateSynonym(ctx context.Context, synonym *model.HotContentProductSynonym) error {
	db := mysql.AispInternalBorm

	params := map[string]interface{}{
		"id": synonym.Id,
	}

	if synonym.BayesFirstCategoryName != "" {
		params["bayes_first_category_name"] = synonym.BayesFirstCategoryName
	}
	if synonym.TakeEffectField != "" {
		params["take_effect_field"] = synonym.TakeEffectField
	}
	if synonym.Keyword != "" {
		params["keyword"] = synonym.Keyword
	}
	if synonym.Synonyms != "" {
		params["synonyms"] = synonym.Synonyms
	}
	if synonym.UpdateUserId != "" {
		params["update_user_id"] = synonym.UpdateUserId
	}
	if synonym.StatusCode != 0 {
		params["status_code"] = synonym.StatusCode
	}

	updateQueryResult := db.Model(synonym).Updates(ctx, params)
	if updateQueryResult.Error != nil {
		log.WithField(ctx, "UpdateSynonym", synonym).Errorf(ctx, "update HotContentProductSynonym err. err=%v", updateQueryResult.Error)
		return updateQueryResult.Error
	}

	return nil
}

func (h *HotContentSynonymDAOImpl) buildCondition(db *borm.ORM, filterParams *model.HotContentSynonymFilterParams) *borm.ORM {
	db = db.Where(borm.Ne{"status_code": model.StatusCodeDeleted})
	if filterParams.BayesFirstCategoryName != "" {
		db = db.Where(borm.Eq{"bayes_first_category_name": filterParams.BayesFirstCategoryName})
	}
	if filterParams.CreateUserId != "" {
		db = db.Where(borm.Eq{"create_user_id": filterParams.CreateUserId})
	}
	if filterParams.Keyword != "" {
		db = db.Where(borm.Eq{"keyword": filterParams.Keyword})
	}

	return db
}

func (h *HotContentSynonymDAOImpl) ListSynonyms(ctx context.Context, filterParams *model.HotContentSynonymFilterParams) ([]*model.HotContentProductSynonym, error) {
	db := mysql.AispInternalBorm

	var synonyms = make([]*model.HotContentProductSynonym, 0)

	db = h.buildCondition(db, filterParams)

	err := db.Offset(filterParams.PageSize*filterParams.Page).Limit(filterParams.PageSize).OrderBy("-created_at").All(ctx, &synonyms)
	if err != nil {
		log.WithField(ctx, "filterParams", filterParams).Errorf(ctx, "ListSynonyms err. err=%v", err)
		return nil, err
	}

	return synonyms, nil
}

func (h *HotContentSynonymDAOImpl) GetTotalCount(ctx context.Context, filterParams *model.HotContentSynonymFilterParams) (int64, error) {
	db := mysql.AispInternalBorm

	db = h.buildCondition(db, filterParams)

	count, err := db.Model(&model.HotContentProductSynonym{}).Count(ctx)
	if err != nil {
		log.WithField(ctx, "filterParams", filterParams).Errorf(ctx, "GetTotalCount err. err=%v", err)
		return 0, err
	}

	return count, nil
}
