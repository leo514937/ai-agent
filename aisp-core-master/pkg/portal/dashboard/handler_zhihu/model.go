package handler_zhihu

import (
	"strings"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	"github.com/samber/lo"
)

type ModelsHandler struct {
	rest.BaseHandler

	modelDAO      dao.ModelDAO
	dorisInternal mysql.Connection
}

func NewModelsHandler() rest.Handler {
	return &ModelsHandler{
		modelDAO:      dao.DefaultModelDAO,
		dorisInternal: resource.DorisAISPInternal,
	}
}

func (h *ModelsHandler) Get(ctx *rest.Context) (rest.Response, error) {
	name := strings.ToLower(strings.TrimSpace(ctx.QueryArgumentWithFallback("name", "")))
	mode := ctx.QueryArgumentWithFallback("mode", "compact")
	models, err := h.modelDAO.ListModels(ctx)
	if err != nil {
		return nil, err
	}

	models = lo.Filter(models, func(model *domainModel.Model, _ int) bool {
		return util.Any(lo.Map(util.List(model.DisplayName, model.Description, model.Name), func(item string, _ int) bool {
			return strings.Contains(strings.ToLower(item), name)
		})...)
	})

	modelDTOs := lo.Map(models, func(model *domainModel.Model, _ int) *ModelDTO {
		return &ModelDTO{
			Name:        model.Name,
			DisplayName: model.DisplayName,
			Description: model.Description,
			OwnerEmail:  model.OwnerEmail,
			Skus: lo.Map(model.Skus, func(sku *domainModel.Sku, _ int) *SkuDTO {
				return &SkuDTO{
					Name:            sku.Name,
					DisplaySubName:  sku.DisplayName,
					DisplayFullName: GetSkuDisplayNameByName(ctx, sku.Name),
					Price: lo.Map(sku.Prices, func(price *domainModel.PriceItem, _ int) *PriceDTO {
						return &PriceDTO{
							InputTokenCentCount:  price.ByInputTokenCount,
							OutputTokenCentCount: price.ByOutputTokenCount,
							ImageCentCount:       price.ByImageCount,
						}
					})[len(sku.Prices)-1],
				}
			}),
			Type:          string(model.Type),
			PlaygroundURL: model.PlaygroundURL,
		}
	})
	if mode == "compact" {
		return ResponseSuccess(modelDTOs)
	}

	rows, err := h.dorisInternal.Query(ctx, "select sku_name, count(distinct caller_app) from model_usage_agg group by sku_name")
	if err != nil {
		return nil, err
	}
	if rows.Err() != nil {
		return nil, rows.Err()
	}

	countMap := map[string]int64{}
	for rows.Next() {
		var (
			skuName  string
			appCount int64
		)
		if err := rows.Scan(&skuName, &appCount); err != nil {
			return nil, err
		}
		countMap[skuName] = appCount
	}

	for _, modelDTO := range modelDTOs {
		modelDTO.AppCount = lo.ToPtr(lo.Sum(lo.Map(modelDTO.Skus, func(skuDTO *SkuDTO, _ int) int64 {
			return countMap[skuDTO.Name]
		})))
	}
	return ResponseSuccess(modelDTOs)
}

type ModelDTO struct {
	Name          string    `json:"name"`
	DisplayName   string    `json:"display_name"`
	Description   string    `json:"description"`
	OwnerEmail    string    `json:"owner_email,omitempty"`
	Skus          []*SkuDTO `json:"skus,omitempty"`
	AppCount      *int64    `json:"app_count,omitempty"`
	Type          string    `json:"type,omitempty"`
	PlaygroundURL string    `json:"playground_url,omitempty"`
}

type PriceDTO struct {
	InputTokenCentCount  int64 `json:"input_token_cent_count"`
	OutputTokenCentCount int64 `json:"output_token_cent_count"`
	ImageCentCount       int64 `json:"image_cent_count"`
}

type SkusHandler struct {
	rest.BaseHandler

	modelDAO dao.ModelDAO
}

func NewSkusHandler() rest.Handler {
	return &SkusHandler{
		modelDAO: dao.DefaultModelDAO,
	}
}

func (h *SkusHandler) Get(ctx *rest.Context) (rest.Response, error) {
	name := strings.ToLower(strings.TrimSpace(ctx.QueryArgumentWithFallback("name", "")))
	skus, err := h.modelDAO.ListSkus(ctx)
	if err != nil {
		return nil, err
	}
	skus = lo.Filter(skus, func(sku *domainModel.Sku, _ int) bool {
		return util.Any(lo.Map(util.List(sku.DisplayName, GetSkuDisplayNameByName(ctx, sku.Name), sku.Name), func(item string, _ int) bool {
			return strings.Contains(strings.ToLower(item), name)
		})...)
	})
	return ResponseSuccess(lo.Map(skus, func(sku *domainModel.Sku, _ int) *SkuDTO {
		return &SkuDTO{
			Name:            sku.Name,
			DisplaySubName:  sku.DisplayName,
			DisplayFullName: GetSkuDisplayNameByName(ctx, sku.Name),
		}
	}))
}

type SkuDTO struct {
	Name            string    `json:"name"`
	DisplaySubName  string    `json:"display_sub_name"`
	DisplayFullName string    `json:"display_full_name"`
	Price           *PriceDTO `json:"price,omitempty"`
}
