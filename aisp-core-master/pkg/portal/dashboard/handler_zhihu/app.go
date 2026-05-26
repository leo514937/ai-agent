package handler_zhihu

import (
	"strings"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"github.com/samber/lo"
)

type AppsHandler struct {
	rest.BaseHandler

	appDAO dao.AppDAO
}

func NewAppsHandler() rest.Handler {
	return &AppsHandler{
		appDAO: dao.DefaultAppDAO,
	}
}

func (h *AppsHandler) Get(ctx *rest.Context) (rest.Response, error) {
	name := strings.ToLower(strings.TrimSpace(ctx.QueryArgumentWithFallback("name", "")))
	bizLineName := strings.TrimSpace(ctx.QueryArgumentWithFallback("biz_line_name", ""))

	apps, err := h.appDAO.ListApp(ctx, name, bizLineName)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(lo.Map[*model.App, *AppDTO](apps, func(item *model.App, _ int) *AppDTO {
		return &AppDTO{
			Name:        item.Name,
			Description: "",
		}
	}))
}

type AppDTO struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}
