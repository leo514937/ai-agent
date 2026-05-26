package dao

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type BmbConversationDAO interface {
	CreateConversion(ctx context.Context, conversation *model.TableBmbConversation) *macro.ServiceError
	GetConversationByID(ctx context.Context, conversationID string) (*model.TableBmbConversation, *macro.ServiceError)
	UpdateConversation(ctx context.Context, conversation *model.TableBmbConversation, updates map[string]interface{}) *macro.ServiceError
	UpdateConversationByConvIDs(ctx context.Context, convIDs []string, updates map[string]interface{}) *macro.ServiceError
}

type BmbConversationDAOImpl struct {
}

func newBmbConversationDAO() BmbConversationDAO {
	return &BmbConversationDAOImpl{}
}

var DefaultBmbConversationDAO BmbConversationDAO

func init() {
	DefaultBmbConversationDAO = newBmbConversationDAO()
}

func (o *BmbConversationDAOImpl) GetConversationByID(ctx context.Context, conversationID string) (*model.TableBmbConversation, *macro.ServiceError) {
	db := mysql.LucaBorm
	var conversation *model.TableBmbConversation
	err := db.Where(borm.Eq{"conv_id": conversationID}).One(ctx, &conversation)
	if err != nil {
		log.WithField(ctx, "conv_id", conversationID).WithError(ctx, err).Errorf(ctx, "[GetConversationByID] failed.")
		if err == borm.ErrRecordNotFound {
			return nil, macro.NewServiceError(macro.SERVICE_CODE_CONVERSATION_NOT_FOUND, err)
		}
		return nil, macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, err)
	}
	return conversation, nil
}

func (o *BmbConversationDAOImpl) UpdateConversation(ctx context.Context, conversation *model.TableBmbConversation, updates map[string]interface{}) *macro.ServiceError {
	db := mysql.LucaBorm
	updateQueryResult := db.Model(&conversation).Updates(ctx, updates)
	if updateQueryResult.Error != nil {
		log.WithField(ctx, "conv_id", conversation.ConvID).WithError(ctx, updateQueryResult.Error).Errorf(ctx, "[UpdateConversation] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, updateQueryResult.Error)
	}
	return nil
}

func (o *BmbConversationDAOImpl) UpdateConversationByConvIDs(ctx context.Context, convIDs []string, updates map[string]interface{}) *macro.ServiceError {
	db := mysql.LucaBorm
	updateQueryResult := db.Table("bmb_conversation").Where(borm.Eq{"conv_id": convIDs}).UpdateRaw(ctx, updates)
	if updateQueryResult.Error != nil {
		log.WithFields(ctx, map[string]interface{}{"conv_ids": convIDs}).WithError(ctx, updateQueryResult.Error).Errorf(ctx, "[UpdateConversationByConvIDs] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, updateQueryResult.Error)
	}
	return nil
}

func (o *BmbConversationDAOImpl) CreateConversion(ctx context.Context, conversation *model.TableBmbConversation) *macro.ServiceError {
	db := mysql.LucaBorm
	result := db.Create(ctx, conversation)
	if result.Error != nil {
		log.WithFields(ctx, map[string]interface{}{"conv_ids": conversation}).WithError(ctx, result.Error).Errorf(ctx, "[CreateConversion] failed.")
		return macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, result.Error)
	}
	return nil
}
