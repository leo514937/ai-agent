package handler

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/zhihaitu/middleware"
)

type FeedBackHandler struct {
	rest.BaseHandler
}

func NewFeedBackHandler() rest.Handler {
	return &FeedBackHandler{}
}

func (k *FeedBackHandler) Post(ctx *rest.Context) (rest.Response, error) {
	account := middleware.GetUserFromContext(ctx)
	if account == nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusParamError), nil
	}
	request := &model.FeedBackRequest{}
	err := ctx.JSONArgs(&request)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[FeedBackHandler Post] JSONArgs failed.")
		return nil, err
	}
	serviceErr := service.FeedBack(ctx, request, account.ID)
	if serviceErr != nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusInnerError), nil
	}
	return model.NewResponseByStatus(ctx, model.ResponseStatusSuccess), nil
}
