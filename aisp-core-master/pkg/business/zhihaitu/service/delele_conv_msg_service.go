package service

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
)

var conversationDao = dao.DefaultBmbConversationDAO

func DeleteConvMsg(ctx context.Context, req *model.DeleteConvMsgRequest, accountID int64) *macro.ServiceError {
	updates := make(map[string]interface{})
	updates["image_id"] = nil
	updates["latex_paper_id"] = nil
	updates["update_time"] = time.Now()
	serviceErr := conversationDao.UpdateConversationByConvIDs(ctx, req.ConvIds, updates)
	if serviceErr != nil {
		return serviceErr
	}
	msgUpdates := map[string]interface{}{
		"is_deleted": model.Deleted,
	}
	return convMessageDao.UpdateConvMessageByConvIDsAndAccountID(ctx, req.ConvIds, accountID, msgUpdates)
}
