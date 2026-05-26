package service

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
)

var reportMsgDao = dao.DefaultReportMsgDAO

func ReportMsg(ctx context.Context, req *model.ReportRequest, accountID int64) *macro.ServiceError {
	reportMsg := &model.TableReportMsg{
		AccountID:    accountID,
		ConvID:       req.ConversationId,
		MsgID:        req.MessageId,
		ReportNo:     util.GenerateRandomString(constant.ReportNoLength),
		AIContent:    req.AIContent,
		ReportReason: req.ReportReason,
		ReportState:  model.ReportState_Process.String(),
		CreateTime:   time.Now(),
		UpdateTime:   time.Now(),
	}
	return reportMsgDao.CreateReportMsg(ctx, reportMsg)
}

func GetReportMsg(ctx context.Context, accountID int64) (*model.ReportMsgInfo, *macro.ServiceError) {
	result := &model.ReportMsgInfo{ReportMsgInfos: make([]*model.ReportMessage, 0)}
	reportMsgs, serviceErr := reportMsgDao.GetReportMsgByAccountIDOrderByID(ctx, accountID)
	if serviceErr != nil {
		return nil, serviceErr
	}
	if len(reportMsgs) == 0 {
		return result, nil
	}
	for _, v := range reportMsgs {
		res := &model.ReportMessage{
			AiContent:    v.AIContent,
			CreateTime:   util.FormatTime2yyyyMMddTHHmmss(v.CreateTime),
			ReportNo:     v.ReportNo,
			ReportReason: v.ReportReason,
			ReportState:  v.ReportState,
		}
		result.ReportMsgInfos = append(result.ReportMsgInfos, res)
	}
	return result, nil
}
