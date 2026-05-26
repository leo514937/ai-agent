package dao

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type BmbConvMessageDAO interface {
	GetConvMessageByMsgID(ctx context.Context, msgID string) (*model.TableBmbConvMessage, *macro.ServiceError)
	GetConvMessageByConvIDAndRole(ctx context.Context, convID string, role int64) ([]*model.TableBmbConvMessage, *macro.ServiceError)
	UpdateConvMessage(ctx context.Context, msg *model.TableBmbConvMessage, updates map[string]interface{}) *macro.ServiceError
	UpdateConvMessageByConvIDsAndAccountID(ctx context.Context, convIDs []string, accountID int64, updates map[string]interface{}) *macro.ServiceError
	UpdateConvMessageByConvID(ctx context.Context, convID string, updates map[string]interface{}) *macro.ServiceError
	UpdateConvMessageByMsgID(ctx context.Context, msgID string, updates map[string]interface{}) *macro.ServiceError
	CreateConvMessage(ctx context.Context, message *model.TableBmbConvMessage) (int64, *macro.ServiceError)
	GetConvMessageByPage(ctx context.Context, convID string, accountId int64, pageNum int, pageSize int) ([]*model.TableBmbConvMessage, *macro.ServiceError)
}

type BmbConvMessageDAOImpl struct {
}

func newBmbConvMessageDAO() BmbConvMessageDAO {
	return &BmbConvMessageDAOImpl{}
}

var DefaultBmbConvMessageDAO BmbConvMessageDAO

func init() {
	DefaultBmbConvMessageDAO = newBmbConvMessageDAO()
}

func (o *BmbConvMessageDAOImpl) GetConvMessageByMsgID(ctx context.Context, msgID string) (*model.TableBmbConvMessage, *macro.ServiceError) {
	db := mysql.LucaBorm
	var convMessage *model.TableBmbConvMessage
	err := db.Where(borm.Eq{"msg_id": msgID}).One(ctx, &convMessage)
	if err != nil {
		log.WithField(ctx, "msg_id", msgID).WithError(ctx, err).Errorf(ctx, "[GetConvMessageByMsgID] failed.")
		if err == borm.ErrRecordNotFound {
			return nil, macro.NewServiceError(macro.SERVICE_CODE_MESSAGE_NOT_FOUND, err)
		}
		return nil, macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, err)
	}
	return convMessage, nil
}

func (o *BmbConvMessageDAOImpl) GetConvMessageByConvIDAndRole(ctx context.Context, convID string, role int64) ([]*model.TableBmbConvMessage, *macro.ServiceError) {
	db := mysql.LucaBorm
	var convMessages []*model.TableBmbConvMessage
	err := db.Where(borm.Eq{"conv_id": convID}).Where(borm.Eq{"role": role}).All(ctx, &convMessages)
	if err != nil {
		log.WithFields(ctx, map[string]interface{}{"conv_id": convID, "role": role}).WithError(ctx, err).Errorf(ctx, "[GetConvMessageByConvIDAndRole] failed.")
		return nil, macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, err)
	}
	return convMessages, nil
}

func (o *BmbConvMessageDAOImpl) GetConvMessageByPage(ctx context.Context, convID string, accountId int64, pageNum int, pageSize int) ([]*model.TableBmbConvMessage, *macro.ServiceError) {
	db := mysql.LucaBorm
	var convMessages []*model.TableBmbConvMessage
	offset := pageNum * pageSize
	err := db.Where(borm.Eq{"conv_id": convID}).Where(borm.Eq{"account_id": accountId}).Where(borm.Eq{"is_deleted": model.NotDeleted}).Offset(offset).Limit(pageSize).OrderBy("-update_time").All(ctx, &convMessages)
	if err != nil {
		log.WithFields(ctx, map[string]interface{}{"conv_id": convID, "account": accountId}).WithError(ctx, err).Errorf(ctx, "[GetConvMessageByPage] failed.")
		return nil, macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, err)
	}
	return convMessages, nil
}

func (o *BmbConvMessageDAOImpl) UpdateConvMessage(ctx context.Context, msg *model.TableBmbConvMessage, updates map[string]interface{}) *macro.ServiceError {
	db := mysql.LucaBorm
	updateQueryResult := db.Model(&msg).Updates(ctx, updates)
	if updateQueryResult.Error != nil {
		log.WithField(ctx, "id", msg.ID).WithError(ctx, updateQueryResult.Error).Errorf(ctx, "[UpdateConvMessageByID] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, updateQueryResult.Error)
	}
	return nil
}

func (o *BmbConvMessageDAOImpl) UpdateConvMessageByConvIDsAndAccountID(ctx context.Context, convIDs []string, accountID int64, updates map[string]interface{}) *macro.ServiceError {
	db := mysql.LucaBorm
	updateQueryResult := db.Table("bmb_conv_message").Where(borm.Eq{"account_id": accountID}).Where(borm.Eq{"conv_id": convIDs}).UpdateRaw(ctx, updates)
	if updateQueryResult.Error != nil {
		log.WithFields(ctx, map[string]interface{}{"conv_ids": convIDs, "account_id": accountID}).WithError(ctx, updateQueryResult.Error).Errorf(ctx, "[UpdateConvMessageByConvIDsAndAccountID] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, updateQueryResult.Error)
	}
	return nil
}

func (o *BmbConvMessageDAOImpl) UpdateConvMessageByConvID(ctx context.Context, convID string, updates map[string]interface{}) *macro.ServiceError {
	db := mysql.LucaBorm
	updateQueryResult := db.Table("bmb_conv_message").Where(borm.Eq{"conv_id": convID}).UpdateRaw(ctx, updates)
	if updateQueryResult.Error != nil {
		log.WithFields(ctx, map[string]interface{}{"conv_id": convID}).WithError(ctx, updateQueryResult.Error).Errorf(ctx, "[UpdateConvMessageByConvID] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, updateQueryResult.Error)
	}
	return nil
}

func (o *BmbConvMessageDAOImpl) UpdateConvMessageByMsgID(ctx context.Context, msgID string, updates map[string]interface{}) *macro.ServiceError {
	db := mysql.LucaBorm
	updateQueryResult := db.Table("bmb_conv_message").Where(borm.Eq{"msg_id": msgID}).UpdateRaw(ctx, updates)
	if updateQueryResult.Error != nil {
		log.WithFields(ctx, map[string]interface{}{"msg_id": msgID}).WithError(ctx, updateQueryResult.Error).Errorf(ctx, "[UpdateConvMessageByMsgID] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, updateQueryResult.Error)
	}
	return nil
}

func (o *BmbConvMessageDAOImpl) CreateConvMessage(ctx context.Context, message *model.TableBmbConvMessage) (int64, *macro.ServiceError) {
	db := mysql.LucaBorm
	result := db.Create(ctx, message)
	if result.Error != nil {
		log.WithFields(ctx, map[string]interface{}{"msg_id": message.MsgID}).WithError(ctx, result.Error).Errorf(ctx, "[CreateConvMessage] failed.")
		return 0, macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, result.Error)
	}
	return result.LastInsertedID, nil
}
