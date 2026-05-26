package handler_ai_daily

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware/auth"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/service"
)

type PlaylistHistoryHandler struct {
	rest.BaseHandler
}

func NewPlaylistHistoryHandler() rest.Handler {
	return &PlaylistHistoryHandler{}
}

func (q *PlaylistHistoryHandler) Get(ctx *rest.Context) (rest.Response, error) {
	userID, err := auth.GetLoginId(ctx.Request)
	if err != nil {
		return nil, rest.HttpServerError
	}
	datas, err := service.DefaultPlaylistService.GetPlaylistHistoryByUserID(ctx, userID)
	if err != nil {
		return nil, rest.HttpServerError
	}
	response := &model.PlaylistHistoryResponse{
		TotalCount: len(datas),
		Items:      datas,
	}
	return &model.Response{
		Code:    0,
		Message: "SUCCESS",
		Data:    response,
	}, nil
}
