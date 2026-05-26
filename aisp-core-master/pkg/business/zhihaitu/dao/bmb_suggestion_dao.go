package dao

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type BmbSuggestionDAO interface {
	CreateSuggestion(ctx context.Context, suggestion *model.TableBmbSuggestion) *macro.ServiceError
	GetSuggestionByAccountID(ctx context.Context, accountID int64) ([]*model.TableBmbSuggestion, *macro.ServiceError)
}

type BmbSuggestionDAOImpl struct {
}

func newBmbSuggestionDAO() BmbSuggestionDAO {
	return &BmbSuggestionDAOImpl{}
}

var DefaultBmbSuggestionDAO BmbSuggestionDAO

func init() {
	DefaultBmbSuggestionDAO = newBmbSuggestionDAO()
}

func (o *BmbSuggestionDAOImpl) CreateSuggestion(ctx context.Context, suggestion *model.TableBmbSuggestion) *macro.ServiceError {
	db := mysql.LucaBorm
	insertQueryResult := db.Create(ctx, &suggestion)
	if insertQueryResult.Error != nil {
		log.WithError(ctx, insertQueryResult.Error).Errorf(ctx, "[CreateSuggestion] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, insertQueryResult.Error)
	}
	return nil
}

func (o *BmbSuggestionDAOImpl) GetSuggestionByAccountID(ctx context.Context, accountID int64) ([]*model.TableBmbSuggestion, *macro.ServiceError) {
	db := mysql.LucaBorm
	var suggestions []*model.TableBmbSuggestion
	err := db.Where(borm.Eq{"account_id": accountID}).All(ctx, &suggestions)
	if err != nil {
		log.WithFields(ctx, map[string]interface{}{"account_id": accountID}).WithError(ctx, err).Errorf(ctx, "[GetSuggestionByAccountID] failed.")
		return nil, macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, err)
	}
	return suggestions, nil
}
