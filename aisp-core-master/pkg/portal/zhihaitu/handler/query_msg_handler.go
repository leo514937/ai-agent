package handler

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/zhihaitu/middleware"
)

type QueryMsgHandler struct {
	rest.BaseHandler
}

func NewQueryMsgHandler() rest.Handler {
	return &QueryMsgHandler{}
}

func (k *QueryMsgHandler) Post(ctx *rest.Context) (rest.Response, error) {
	account := middleware.GetUserFromContext(ctx)
	if account == nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusParamError), nil
	}
	request := &model.QueryMsgRequest{}
	err := ctx.JSONArgs(&request)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[QueryMsgHandler Post] JSONArgs failed.")
		return nil, err
	}
	resp, serviceErr := service.QueryMessage(ctx, request, account.ID)
	if serviceErr != nil {
		if serviceErr.Code() == int64(macro.SERVICE_CODE_MESSAGE_NOT_FOUND) {
			return model.NewResponseByStatus(ctx, model.ResponseStatusParamError), nil
		}
		return model.NewResponseByStatus(ctx, model.ResponseStatusInnerError), nil
	}
	return &model.Response{
		ResponseStatus: model.ResponseStatusSuccess,
		Data:           resp,
	}, nil
}
