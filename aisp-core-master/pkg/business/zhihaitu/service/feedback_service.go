package service

import (
	"context"
	"strings"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
)

var auditDao = dao.DefaultBmbAuditDAO

func FeedBack(ctx context.Context, req *model.FeedBackRequest, accountID int64) *macro.ServiceError {
	// 用户申诉:用户提问没有过安审
	if req.Role == model.RoleEnum_User.String() && strings.Contains(req.FeedbackMsg, constant.USER_COMPLAIN_TEXT) {
		updates := make(map[string]interface{})
		updates["is_complained"] = model.ComplainedEnum_Complained
		return auditDao.UpdateAuditByAccountIDAndQuestionID(ctx, accountID, req.MessageID, updates)
	}
	// 用户申诉:AI回答内容没有过安审
	if strings.Contains(req.FeedbackMsg, constant.USER_COMPLAIN_TEXT) {
		updates := make(map[string]interface{})
		updates["is_complained"] = model.ComplainedEnum_Complained
		serviceErr := auditDao.UpdateAuditByAccountIDAndQuestionID(ctx, accountID, req.MessageID, updates)
		if serviceErr != nil {
			return serviceErr
		}
	}
	convMsg, serviceErr := convMessageDao.GetConvMessageByMsgID(ctx, req.MessageID)
	if serviceErr != nil {
		return serviceErr
	}
	updates := make(map[string]interface{})
	if req.Rating != "" && req.Rating != model.RatingEnum_No.String() {
		rating := model.RatingEnum_Down.Flag()
		if req.Rating == model.RatingEnum_Up.String() {
			rating = model.RatingEnum_Up.Flag()
		}
		updates["rating"] = rating
	}
	if req.FeedbackMsg != "" {
		updates["feedback_msg"] = req.FeedbackMsg
	}
	if req.FeedbackAction != "" {
		if req.FeedbackAction == model.FeedbackActionEnum_Copy.String() {
			convMsg.FeedbackAction.IsCopied = true
		} else if req.FeedbackAction == model.FeedbackActionEnum_Regenerate.String() {
			convMsg.FeedbackAction.IsRegen = true
		}
		updates["feedback_action"] = convMsg.FeedbackAction
	}
	updates["update_time"] = time.Now()
	return convMessageDao.UpdateConvMessage(ctx, convMsg, updates)
}
