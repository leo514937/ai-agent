package handler_ai_daily

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware/auth"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type QueryPlaylistHandler struct {
	rest.BaseHandler
}

func NewQueryPlaylistHandler() rest.Handler {
	return &QueryPlaylistHandler{}
}

func (q *QueryPlaylistHandler) Get(ctx *rest.Context) (rest.Response, error) {
	userID, err := auth.GetLoginId(ctx.Request)
	if err != nil {
		return nil, rest.HttpServerError
	}
	date := ctx.QueryArgument("date")
	token := ctx.QueryArgument("token")
	req := &model.QueryPlaylistRequest{
		UserID: userID,
		Date:   date,
		Token:  token,
		Source: model.RequestSourceNormal,
	}
	logger := log.WithFields(ctx, map[string]interface{}{"user_id": userID, "date": date, "token": token, "source": req.Source})
	// 获取当前图配置
	bizRequestContext := entities.NewRequestContextFromAIDailyRequest(req)
	_, _, _, err = graph.RunGraph(ctx, bizRequestContext, nil)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "run QueryPlaylist graph failed => BuildQuery")
		return nil, rest.HttpServerError
	}
	return &model.Response{
		Code:    0,
		Message: "SUCCESS",
		Data:    bizRequestContext.GetPlayListData().Response,
	}, nil
}
