package handler

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/zhihaitu/middleware"
)

type SuggestionHandler struct {
	rest.BaseHandler
}

func NewSuggestionHandler() rest.Handler {
	return &SuggestionHandler{}
}

func (k *SuggestionHandler) Post(ctx *rest.Context) (rest.Response, error) {
	account := middleware.GetUserFromContext(ctx)
	if account == nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusParamError), nil
	}
	request := &model.SuggestionRequest{}
	err := ctx.JSONArgs(&request)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[SuggestionHandler Post] JSONArgs failed.")
		return nil, err
	}
	serviceErr := service.Suggestion(ctx, request, account.ID)
	if serviceErr != nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusServerError), nil
	}
	return model.NewResponseByStatus(ctx, model.ResponseStatusSuccess), nil
}

func (k *SuggestionHandler) Get(ctx *rest.Context) (rest.Response, error) {
	account := middleware.GetUserFromContext(ctx)
	if account == nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusParamError), nil
	}
	resp, serviceErr := service.GetUserSuggestion(ctx, account.ID)
	if serviceErr != nil {
		return model.NewResponseByStatus(ctx, model.ResponseStatusServerError), nil
	}
	return &model.Response{
		ResponseStatus: model.ResponseStatusSuccess,
		Data:           resp,
	}, nil
}
