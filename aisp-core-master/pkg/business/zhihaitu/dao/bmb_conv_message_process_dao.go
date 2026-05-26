package dao

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type BmbConvMessageProcessDAO interface {
	GetConvMessageProcessByConvIDAndConditions(ctx context.Context, convID string, conditionMap map[string]interface{}) ([]*model.TableBmbConvMessageProcess, *macro.ServiceError)
}

type BmbConvMessageProcessDAOImpl struct {
}

func newBmbConvMessageProcessDAO() BmbConvMessageProcessDAO {
	return &BmbConvMessageProcessDAOImpl{}
}

var DefaultBmbConvMessageProcessDAO BmbConvMessageProcessDAO

func init() {
	DefaultBmbConvMessageProcessDAO = newBmbConvMessageProcessDAO()
}

func (o *BmbConvMessageProcessDAOImpl) GetConvMessageProcessByConvIDAndConditions(ctx context.Context, convID string, conditionMap map[string]interface{}) ([]*model.TableBmbConvMessageProcess, *macro.ServiceError) {
	db := mysql.LucaBorm
	conditions := borm.Eq{
		"conv_id": convID,
	}
	for k, v := range conditionMap {
		conditions[k] = v
	}
	var convMessageProcesses []*model.TableBmbConvMessageProcess
	err := db.Where(conditions).All(ctx, &convMessageProcesses)
	if err != nil {
		log.WithField(ctx, "conv_id", convID).WithError(ctx, err).Errorf(ctx, "[GetConvMessageProcessByConvIDAndConditions] failed.")
		return nil, macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, err)
	}
	return convMessageProcesses, nil
}
