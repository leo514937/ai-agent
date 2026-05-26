package dao

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type BmbAuditDAO interface {
	UpdateAuditByAccountIDAndQuestionID(ctx context.Context, accountID int64, questionID string, updates map[string]interface{}) *macro.ServiceError
	UpdateAuditByAccountIDAndAnswerID(ctx context.Context, accountID int64, answerID string, updates map[string]interface{}) *macro.ServiceError
}

type BmbAuditDAOImpl struct {
}

func newBmbAuditDAO() BmbAuditDAO {
	return &BmbAuditDAOImpl{}
}

var DefaultBmbAuditDAO BmbAuditDAO

func init() {
	DefaultBmbAuditDAO = newBmbAuditDAO()
}

func (o *BmbAuditDAOImpl) UpdateAuditByAccountIDAndQuestionID(ctx context.Context, accountID int64, questionID string, updates map[string]interface{}) *macro.ServiceError {
	db := mysql.LucaBorm
	updateQueryResult := db.Table("bmb_audit").Where(borm.Eq{"account_id": accountID, "question_id": questionID}).UpdateRaw(ctx, updates)
	if updateQueryResult.Error != nil {
		log.WithFields(ctx, map[string]interface{}{"question_id": questionID}).WithError(ctx, updateQueryResult.Error).Errorf(ctx, "[UpdateAuditByQuestionID] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, updateQueryResult.Error)
	}
	return nil
}

func (o *BmbAuditDAOImpl) UpdateAuditByAccountIDAndAnswerID(ctx context.Context, accountID int64, answerID string, updates map[string]interface{}) *macro.ServiceError {
	db := mysql.LucaBorm
	updateQueryResult := db.Table("bmb_audit").Where(borm.Eq{"account_id": accountID, "answer_id": answerID}).UpdateRaw(ctx, updates)
	if updateQueryResult.Error != nil {
		log.WithField(ctx, "answer_id", answerID).WithError(ctx, updateQueryResult.Error).Errorf(ctx, "[UpdateAuditByAnswerID] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, updateQueryResult.Error)
	}
	return nil
}
