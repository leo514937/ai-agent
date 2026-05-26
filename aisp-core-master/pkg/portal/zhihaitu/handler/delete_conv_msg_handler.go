package handler

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/zhihaitu/middleware"
)

type DeleteConvMsgHandler struct {
	rest.BaseHandler
}

func NewDeleteConvMsgHandler() rest.Handler {
	return &DeleteConvMsgHandler{}
}

func (k *DeleteConvMsgHandler) Post(ctx *rest.Context) (rest.Response, error) {
	account := middleware.GetUserFromContext(ctx)
	if account == nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusParamError), nil
	}
	request := &model.DeleteConvMsgRequest{}
	err := ctx.JSONArgs(&request)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[DeleteConvMsgHandler Post] JSONArgs failed.")
		return nil, err
	}
	serviceErr := service.DeleteConvMsg(ctx, request, account.ID)
	if serviceErr != nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusInnerError), nil
	}
	return model.NewResponseByStatus(ctx, model.ResponseStatusSuccess), nil
}
