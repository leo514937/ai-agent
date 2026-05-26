package dao

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

// ----------------知识库 begin --------------------

// KnowledgeBaseV2DAO 知识库，aka 知识增强
type KnowledgeBaseV2DAO interface {
	ListByParams(ctx context.Context, params *model.FilterParams) ([]*model.KnowledgeBaseV2, error)
	GetTotalCount(ctx context.Context, params *model.FilterParams) (int64, error)
	Insert(ctx context.Context, knowledgeBase []*model.KnowledgeBaseV2) (mysql.Result, error)
	Update(ctx context.Context, knowledgeBase *model.KnowledgeBaseV2) error
	GetById(ctx context.Context, id int64) (*model.KnowledgeBaseV2, error)
	GetByIds(ctx context.Context, ids []int64) ([]*model.KnowledgeBaseV2, error)
}

type KnowledgeBaseV2DAOImpl struct {
}

func newKnowledgeBaseV2DAO() *KnowledgeBaseV2DAOImpl {
	return &KnowledgeBaseV2DAOImpl{}
}

var DefaultKnowledgeBaseV2DAO *KnowledgeBaseV2DAOImpl

func init() {
	DefaultKnowledgeBaseV2DAO = newKnowledgeBaseV2DAO()
}

func buildKnowledgeBaseSqlCondition(db *borm.ORM, params *model.FilterParams) *borm.ORM {
	condition := buildCommonSqlCondition(db, params)
	if params.Query != "" {
		query := "%" + params.Query + "%"
		condition = condition.Where(borm.OR{borm.Like{"key_words": query}, borm.Like{"knowledge_content": query}})
	}

	return condition
}

func buildCommonSqlCondition(db *borm.ORM, params *model.FilterParams) *borm.ORM {
	condition := db

	if params.Status != 0 {
		condition = condition.Where(borm.Eq{"status_code": params.Status})
	} else {
		condition = condition.Where(borm.Ne{"status_code": model.OperationBaseStatusDeleted})
	}

	if params.CreateUserId != "" {
		createUserId := "%" + params.CreateUserId + "%"
		condition = condition.Where(borm.Like{"create_user_id": createUserId})
	}

	if params.UpdateUserId != "" {
		updateUserId := "%" + params.UpdateUserId + "%"
		condition = condition.Where(borm.Like{"update_user_id": updateUserId})
	}

	if params.CreatedAtBegin != nil && params.CreatedAtEnd != nil {
		condition = condition.Where(borm.GTE{"created_at": params.CreatedAtBegin}).Where(borm.LT{"created_at": params.CreatedAtEnd})
	}

	if params.UpdatedAtBegin != nil && params.UpdatedAtEnd != nil {
		condition = condition.Where(borm.GTE{"updated_at": params.UpdatedAtBegin}).Where(borm.LT{"updated_at": params.UpdatedAtEnd})
	}

	if params.Scene != "" {
		condition = condition.Where(borm.Eq{"scene": params.Scene})
	}

	return condition
}

func (o KnowledgeBaseV2DAOImpl) GetTotalCount(ctx context.Context, params *model.FilterParams) (int64, error) {
	db := mysql.AispInternalBorm

	var knowledgeBase model.KnowledgeBaseV2
	totalCount, err := buildKnowledgeBaseSqlCondition(db, params).Model(&knowledgeBase).Count(ctx)
	if err != nil {
		return 0, err
	}
	return totalCount, nil
}

func (o KnowledgeBaseV2DAOImpl) ListByParams(ctx context.Context, params *model.FilterParams) ([]*model.KnowledgeBaseV2, error) {
	var knowledgeBases []*model.KnowledgeBaseV2
	offset := params.PageSize * params.Page

	db := mysql.AispInternalBorm

	// "-created_at" 表示倒序
	var err = buildKnowledgeBaseSqlCondition(db, params).Offset(offset).Limit(params.PageSize).OrderBy("-created_at").All(ctx, &knowledgeBases)
	if err != nil {
		return nil, err
	}
	return knowledgeBases, nil
}

func (o KnowledgeBaseV2DAOImpl) Insert(ctx context.Context, knowledgeBases []*model.KnowledgeBaseV2) (mysql.Result, error) {
	db := mysql.AispInternalBorm

	insertResult := db.CreateMany(ctx, knowledgeBases)
	if insertResult.Error != nil {
		return mysql.Result{}, insertResult.Error
	}
	return mysql.Result{LastInsertedID: insertResult.LastInsertedID, AffectedRows: insertResult.AffectedRows}, nil
}

func (o KnowledgeBaseV2DAOImpl) Update(ctx context.Context, knowledgeBase *model.KnowledgeBaseV2) error {
	db := mysql.AispInternalBorm

	params := map[string]interface{}{
		"id":             knowledgeBase.Id,
		"update_user_id": knowledgeBase.UpdateUserId,
	}
	if knowledgeBase.KeyWords != "" {
		params["key_words"] = knowledgeBase.KeyWords
	}
	if knowledgeBase.KnowledgeContent != "" {
		params["knowledge_content"] = knowledgeBase.KnowledgeContent
	}
	if knowledgeBase.StatusCode != 0 {
		params["status_code"] = knowledgeBase.StatusCode
	}

	updateQueryResult := db.Model(&knowledgeBase).Updates(ctx, params)
	return updateQueryResult.Error
}

func (o KnowledgeBaseV2DAOImpl) GetById(ctx context.Context, id int64) (*model.KnowledgeBaseV2, error) {
	db := mysql.AispInternalBorm

	var knowledgeBase *model.KnowledgeBaseV2
	err := db.FindByPK(ctx, &knowledgeBase, id)
	if err != nil {
		return &model.KnowledgeBaseV2{}, err
	} else {
		return knowledgeBase, nil
	}
}

func (o KnowledgeBaseV2DAOImpl) GetByIds(ctx context.Context, ids []int64) ([]*model.KnowledgeBaseV2, error) {
	db := mysql.AispInternalBorm

	var knowledgeBases []*model.KnowledgeBaseV2
	err := db.FindByPKs(ctx, &knowledgeBases, ids)
	if err != nil {
		return nil, err
	} else {
		return knowledgeBases, nil
	}
}

// ----------------知识库 end --------------------

// ----------------静态库 begin --------------------

// StaticBaseDAO 静态库，aka 红线必答
type StaticBaseDAO interface {
	ListByParams(ctx context.Context, params *model.FilterParams) ([]*model.StaticBase, error)
	ListOnlineByQuestionHash(ctx context.Context, queryHash int64) ([]*model.StaticBase, error)
	GetTotalCount(ctx context.Context, params *model.FilterParams) (int64, error)
	Insert(ctx context.Context, staticBase []*model.StaticBase) (mysql.Result, error)
	Update(ctx context.Context, staticBase *model.StaticBase) error
	GetById(ctx context.Context, id int64) (*model.StaticBase, error)
	GetByIds(ctx context.Context, ids []int64) ([]*model.StaticBase, error)
}

type StaticBaseDAOImpl struct {
}

func newStaticBaseDAO() *StaticBaseDAOImpl {
	return &StaticBaseDAOImpl{}
}

var DefaultStaticBaseDAO *StaticBaseDAOImpl

func init() {
	DefaultStaticBaseDAO = newStaticBaseDAO()
}

func buildStaticBaseSqlCondition(db *borm.ORM, params *model.FilterParams) *borm.ORM {
	condition := buildCommonSqlCondition(db, params)
	if params.Query != "" {
		query := "%" + params.Query + "%"
		condition = condition.Where(borm.OR{borm.Like{"question": query}, borm.Like{"answer": query}})
	}

	return condition
}

func (o StaticBaseDAOImpl) GetTotalCount(ctx context.Context, params *model.FilterParams) (int64, error) {
	db := mysql.AispInternalBorm

	var staticBase model.StaticBase

	totalCount, err := buildStaticBaseSqlCondition(db, params).Model(&staticBase).Count(ctx)
	if err != nil {
		return 0, err
	}
	return totalCount, nil
}

func (o StaticBaseDAOImpl) ListByParams(ctx context.Context, params *model.FilterParams) ([]*model.StaticBase, error) {
	var staticBases []*model.StaticBase
	offset := params.PageSize * params.Page

	db := mysql.AispInternalBorm

	// "-created_at" 表示倒序
	var err = buildStaticBaseSqlCondition(db, params).Offset(offset).Limit(params.PageSize).OrderBy("-created_at").All(ctx, &staticBases)
	if err != nil {
		return nil, err
	}
	return staticBases, nil
}

func (o StaticBaseDAOImpl) ListOnlineByQuestionHash(ctx context.Context, questionHash int64) ([]*model.StaticBase, error) {
	var staticBases []*model.StaticBase

	db := mysql.AispInternalBorm

	var err = db.Where(borm.Eq{"no_symbol_question_hash": questionHash}).Where(borm.Eq{"status_code": model.OperationBaseStatusOnline}).All(ctx, &staticBases)
	if err != nil {
		return nil, err
	}
	return staticBases, nil
}

func (o StaticBaseDAOImpl) Insert(ctx context.Context, staticBases []*model.StaticBase) (mysql.Result, error) {
	db := mysql.AispInternalBorm

	insertResult := db.CreateMany(ctx, staticBases)
	if insertResult.Error != nil {
		return mysql.Result{}, insertResult.Error
	}
	return mysql.Result{LastInsertedID: insertResult.LastInsertedID, AffectedRows: insertResult.AffectedRows}, nil
}

func (o StaticBaseDAOImpl) Update(ctx context.Context, staticBase *model.StaticBase) error {
	db := mysql.AispInternalBorm

	params := map[string]interface{}{
		"id":             staticBase.Id,
		"update_user_id": staticBase.UpdateUserId,
	}

	if staticBase.Question != "" {
		params["question"] = staticBase.Question
	}
	if staticBase.Answer != "" {
		params["answer"] = staticBase.Answer
	}
	if staticBase.StatusCode != 0 {
		params["status_code"] = staticBase.StatusCode
	}
	if staticBase.NoSymbolQuestionHash != 0 {
		params["no_symbol_question_hash"] = staticBase.NoSymbolQuestionHash
	}
	if staticBase.Scene != "" {
		params["scene"] = staticBase.Scene
	}

	updateQueryResult := db.Model(&staticBase).Updates(ctx, params)
	return updateQueryResult.Error
}

func (o StaticBaseDAOImpl) GetById(ctx context.Context, id int64) (*model.StaticBase, error) {
	db := mysql.AispInternalBorm

	var staticBase *model.StaticBase
	err := db.FindByPK(ctx, &staticBase, id)
	if err != nil {
		return &model.StaticBase{}, err
	} else {
		return staticBase, nil
	}
}

func (o StaticBaseDAOImpl) GetByIds(ctx context.Context, ids []int64) ([]*model.StaticBase, error) {
	db := mysql.AispInternalBorm

	var staticBases []*model.StaticBase
	err := db.FindByPKs(ctx, &staticBases, ids)
	if err != nil {
		return nil, err
	} else {
		return staticBases, nil
	}
}

// ----------------faq库 begin --------------------

const selectMaxSize = 1000

// FaqBaseDAO faq库
type FaqBaseDAO interface {
	ListByParams(ctx context.Context, params *model.FilterParams) ([]*model.FaqBase, error)
	GetTotalCount(ctx context.Context, params *model.FilterParams) (int64, error)
	Insert(ctx context.Context, faqBases []*model.FaqBase) (mysql.Result, error)
	Update(ctx context.Context, faqBase *model.FaqBase) error
	GetById(ctx context.Context, id int64) (*model.FaqBase, error)
	GetByIds(ctx context.Context, ids []int64) ([]*model.FaqBase, error)
}

type FaqBaseDAOImpl struct {
}

func newFaqBaseDAO() *FaqBaseDAOImpl {
	return &FaqBaseDAOImpl{}
}

var DefaultFaqBaseDAO *FaqBaseDAOImpl

func init() {
	DefaultFaqBaseDAO = newFaqBaseDAO()
}

func buildFaqBaseSqlCondition(db *borm.ORM, params *model.FilterParams) *borm.ORM {
	condition := buildCommonSqlCondition(db, params)
	if params.Query != "" {
		query := "%" + params.Query + "%"
		condition = condition.Where(borm.OR{borm.Like{"question": query}, borm.Like{"answer": query}})
	}
	if len(params.MatchType) != 0 {
		matchType := conf.CreateFaqMatchTypeCombinations(params.MatchType)
		condition = condition.Where(borm.Eq{"match_type": matchType})
	}

	return condition
}

func (o FaqBaseDAOImpl) GetTotalCount(ctx context.Context, params *model.FilterParams) (int64, error) {
	db := mysql.AispInternalBorm

	var faqBase model.FaqBase

	totalCount, err := buildFaqBaseSqlCondition(db, params).Model(&faqBase).Count(ctx)
	if err != nil {
		return 0, err
	}
	return totalCount, nil
}

func (o FaqBaseDAOImpl) ListByParams(ctx context.Context, params *model.FilterParams) ([]*model.FaqBase, error) {
	db := mysql.AispInternalBorm

	if params.PageSize > selectMaxSize {
		var faqBaseArray []*model.FaqBase
		page := params.PageSize/selectMaxSize + 1

		originOffset := params.PageSize * params.Page

		for i := 0; i < page; i++ {
			var faqBases []*model.FaqBase

			offset := originOffset + selectMaxSize*i
			var err = buildFaqBaseSqlCondition(db, params).Offset(offset).Limit(selectMaxSize).OrderBy("-created_at", "id").All(ctx, &faqBases)
			if err != nil {
				log.WithError(ctx, err).Infof(ctx, "ListByParams error. offset=%d, size=%d", offset, selectMaxSize)
				return nil, err
			}
			if len(faqBases) == 0 {
				break
			}

			faqBaseArray = append(faqBaseArray, faqBases...)
		}

		return faqBaseArray, nil
	} else {
		var faqBases []*model.FaqBase
		offset := params.PageSize * params.Page

		// "-created_at" 表示倒序
		var err = buildFaqBaseSqlCondition(db, params).Offset(offset).Limit(params.PageSize).OrderBy("-created_at").All(ctx, &faqBases)
		if err != nil {
			log.WithError(ctx, err).Infof(ctx, "ListByParams error. offset=%d, size=%d", offset, params.PageSize)
			return nil, err
		}

		return faqBases, nil
	}
}

func (o FaqBaseDAOImpl) Insert(ctx context.Context, faqBases []*model.FaqBase) (mysql.Result, error) {
	db := mysql.AispInternalBorm

	insertResult := db.CreateMany(ctx, faqBases)
	if insertResult.Error != nil {
		return mysql.Result{}, insertResult.Error
	}
	return mysql.Result{LastInsertedID: insertResult.LastInsertedID, AffectedRows: insertResult.AffectedRows}, nil
}

func (o FaqBaseDAOImpl) Update(ctx context.Context, faqBase *model.FaqBase) error {
	db := mysql.AispInternalBorm

	params := map[string]interface{}{
		"id":             faqBase.Id,
		"update_user_id": faqBase.UpdateUserId,
	}

	if faqBase.Question != "" {
		params["question"] = faqBase.Question
	}
	if faqBase.Answer != "" {
		params["answer"] = faqBase.Answer
	}
	if faqBase.StatusCode != 0 {
		params["status_code"] = faqBase.StatusCode
	}
	if faqBase.MatchType != 0 {
		params["match_type"] = faqBase.MatchType
	}
	if faqBase.Scene != "" {
		params["scene"] = faqBase.Scene
	}

	updateQueryResult := db.Model(&faqBase).Updates(ctx, params)
	return updateQueryResult.Error
}

func (o FaqBaseDAOImpl) GetById(ctx context.Context, id int64) (*model.FaqBase, error) {
	db := mysql.AispInternalBorm

	var faqBase *model.FaqBase
	err := db.FindByPK(ctx, &faqBase, id)
	if err != nil {
		return &model.FaqBase{}, err
	} else {
		return faqBase, nil
	}
}

func (o FaqBaseDAOImpl) GetByIds(ctx context.Context, ids []int64) ([]*model.FaqBase, error) {
	db := mysql.AispInternalBorm

	var faqBases []*model.FaqBase
	err := db.FindByPKs(ctx, &faqBases, ids)
	if err != nil {
		return nil, err
	} else {
		return faqBases, nil
	}
}
