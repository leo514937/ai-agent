package handler

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/zhihaitu/middleware"
)

type ReportHandler struct {
	rest.BaseHandler
}

func NewReportHandler() rest.Handler {
	return &ReportHandler{}
}

func (k *ReportHandler) Post(ctx *rest.Context) (rest.Response, error) {
	account := middleware.GetUserFromContext(ctx)
	if account == nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusParamError), nil
	}
	request := &model.ReportRequest{}
	err := ctx.JSONArgs(&request)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[ReportHandler] JSONArgs failed.")
		return nil, err
	}
	serviceErr := service.ReportMsg(ctx, request, account.ID)
	if serviceErr != nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusServerError), nil
	}
	return model.NewResponseByStatus(ctx, model.ResponseStatusSuccess), nil
}

type GetReportMsgHandler struct {
	rest.BaseHandler
}

func NewGetReportMsgHandler() rest.Handler {
	return &GetReportMsgHandler{}
}

func (k *GetReportMsgHandler) Post(ctx *rest.Context) (rest.Response, error) {
	account := middleware.GetUserFromContext(ctx)
	if account == nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusParamError), nil
	}
	resp, serviceErr := service.GetReportMsg(ctx, account.ID)
	if serviceErr != nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusServerError), nil
	}
	return &model.Response{
		ResponseStatus: model.ResponseStatusSuccess,
		Data:           resp,
	}, nil
}
