package dao

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type ReportMsgDAO interface {
	CreateReportMsg(ctx context.Context, msg *model.TableReportMsg) *macro.ServiceError
	GetReportMsgByAccountIDOrderByID(ctx context.Context, accountID int64) ([]*model.TableReportMsg, *macro.ServiceError)
}

type ReportMsgDAOImpl struct {
}

func newReportMsgDAO() ReportMsgDAO {
	return &ReportMsgDAOImpl{}
}

var DefaultReportMsgDAO ReportMsgDAO

func init() {
	DefaultReportMsgDAO = newReportMsgDAO()
}

func (o *ReportMsgDAOImpl) CreateReportMsg(ctx context.Context, msg *model.TableReportMsg) *macro.ServiceError {
	db := mysql.LucaBorm
	insertQueryResult := db.Create(ctx, &msg)
	if insertQueryResult.Error != nil {
		log.WithError(ctx, insertQueryResult.Error).Errorf(ctx, "[CreateReportMsg] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, insertQueryResult.Error)
	}
	return nil
}

func (o *ReportMsgDAOImpl) GetReportMsgByAccountIDOrderByID(ctx context.Context, accountID int64) ([]*model.TableReportMsg, *macro.ServiceError) {
	db := mysql.LucaBorm
	var reportMsgs []*model.TableReportMsg
	err := db.Where(borm.Eq{"account_id": accountID}).OrderBy("-id").All(ctx, &reportMsgs)
	if err != nil {
		log.WithFields(ctx, map[string]interface{}{"account_id": accountID}).WithError(ctx, err).Errorf(ctx, "[GetReportMsgByAccountIDOrderByID] failed.")
		return nil, macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, err)
	}
	return reportMsgs, nil
}
