package service

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
)

var convMessageDao = dao.DefaultBmbConvMessageDAO
var convMessageProcessDao = dao.DefaultBmbConvMessageProcessDAO

func QueryMessage(ctx context.Context, req *model.QueryMsgRequest, accountID int64) (*model.MessageInfo, *macro.ServiceError) {

	msg, serviceErr := convMessageDao.GetConvMessageByMsgID(ctx, req.MessageID)
	if serviceErr != nil {
		return nil, serviceErr
	}
	conditionMap := map[string]interface{}{
		"msg_id":     req.MessageID,
		"account_id": accountID,
		"is_deleted": model.NotDeleted,
	}
	msgProcesses, serviceErr := convMessageProcessDao.GetConvMessageProcessByConvIDAndConditions(ctx, req.ConversationID, conditionMap)
	if serviceErr != nil {
		return nil, serviceErr
	}
	resp := &model.MessageInfo{
		MsgId:          req.MessageID,
		MsgType:        model.MessageType(msg.MsgType),
		Output:         msg.Content,
		CostTimeMillis: msg.CostTimeMillis,
		MsgStates:      convertMessageState(msgProcesses),
		State:          model.MessageTaskState(msg.State),
		StopEnum:       model.MsgStopEnum(util.GetSafeString(msg.StopEnum)),
	}
	return resp, nil
}

func convertMessageState(msgProcesses []*model.TableBmbConvMessageProcess) []*model.MessageState {
	result := make([]*model.MessageState, 0)
	for _, v := range msgProcesses {
		newState := &model.MessageState{Tip: v.Tip}
		result = append(result, newState)
	}
	return result
}
