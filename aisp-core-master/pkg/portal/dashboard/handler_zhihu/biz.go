package handler_zhihu

import (
	"sort"
	"strings"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"github.com/samber/lo"
)

type BizLinesHandler struct {
	rest.BaseHandler

	appDAO dao.AppDAO
}

func NewBizLinesHandler() *BizLinesHandler {
	return &BizLinesHandler{
		appDAO: dao.DefaultAppDAO,
	}
}

func (h *BizLinesHandler) Get(ctx *rest.Context) (rest.Response, error) {
	name := strings.ToLower(strings.TrimSpace(ctx.QueryArgumentWithFallback("name", "")))

	apps, err := h.appDAO.ListApp(ctx, "", "")
	if err != nil {
		return nil, err
	}

	bizLineNames := lo.Map(apps, func(item *model.App, _ int) string {
		return item.OwnerBizLineName
	})
	bizLineNames = lo.Uniq(bizLineNames)
	bizLineNameWithLevel := lo.Map(bizLineNames, func(item string, _ int) (levels []string) {
		parts := strings.Split(item, "-")
		for i := range parts {
			levels = append(levels, strings.Join(parts[:i+1], "-"))
		}
		return
	})
	bizLineNames = lo.Flatten(bizLineNameWithLevel)
	bizLineNames = lo.Filter(bizLineNames, func(item string, _ int) bool {
		return strings.Contains(strings.ToLower(item), name)
	})
	bizLineNames = lo.Uniq(bizLineNames)
	sort.Slice(bizLineNames, func(i, j int) bool {
		return bizLineNames[i] < bizLineNames[j]
	})

	bizLines := lo.Map(bizLineNames, func(item string, _ int) *BizLineDTO {
		return &BizLineDTO{
			Name: item,
		}
	})
	return ResponseSuccess(bizLines)
}

type BizLineDTO struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}
