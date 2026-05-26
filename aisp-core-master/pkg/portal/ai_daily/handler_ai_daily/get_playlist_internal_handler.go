package handler_ai_daily

import (
	"strconv"
	"time"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/one-rpc-go/thrift-user_core/user_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type GetPlaylistInternalHandler struct {
	rest.BaseHandler
	userCoreRpc rpc.UserCoreService
}

func NewGetPlaylistInternalHandler() rest.Handler {
	return &GetPlaylistInternalHandler{
		userCoreRpc: impl.DefaultUserCoreServiceImpl,
	}
}

func (q *GetPlaylistInternalHandler) Get(ctx *rest.Context) (rest.Response, error) {
	date := ctx.QueryArgument("date")
	if date == "" {
		date = time.Now().Format("2006-01-02")
	}
	userIDStr := ctx.QueryArgument("member_id")
	userID, err := strconv.ParseInt(userIDStr, 10, 64)
	if err != nil {
		return nil, rest.HttpBadRequestError
	}
	req := &model.QueryPlaylistRequest{
		UserID: userID,
		Date:   date,
		Source: model.RequestSourceInternal,
	}
	logger := log.WithFields(ctx, map[string]interface{}{"user_id": userID, "date": date})
	// 获取当前图配置
	bizRequestContext := entities.NewRequestContextFromAIDailyRequest(req)
	_, _, _, err = graph.RunGraph(ctx, bizRequestContext, nil)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "run GetPlaylistInternal graph failed => BuildQuery")
		return nil, rest.HttpServerError
	}
	data := &model.InternalResponseData{
		Date:     date,
		UserName: bizRequestContext.GetPlayListData().UserName,
		Datas:    bizRequestContext.GetPlayListData().FinalQuestionDetails,
	}
	userInfo, err := q.userCoreRpc.BatchGetUserByIds(ctx, []int64{req.UserID}, []string{user_core_thrift.ProfileField})
	if err != nil {
		logger.Errorf(ctx, "[GetPlaylistInternalHandler] BatchGetUserByIds error: %v userID=%v", err, req.UserID)
	} else {
		if val, ok := userInfo[req.UserID]; ok && val.GetProfile() != nil {
			data.UserName = val.GetProfile().GetFullname()
		}
	}
	return &model.Response{
		Code:    0,
		Message: "SUCCESS",
		Data:    data,
	}, nil
}
