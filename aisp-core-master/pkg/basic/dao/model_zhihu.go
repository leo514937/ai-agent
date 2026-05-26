package dao

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

type ModelDAO interface {
	ListModels(ctx context.Context) ([]*domainModel.Model, error)
	GetModelByName(ctx context.Context, modelName string) (*domainModel.Model, error)
	ListSkus(ctx context.Context) ([]*domainModel.Sku, error)
}

type ModelDAOImpl struct {
	configClient config.Client
}

func newModelDAOImpl() *ModelDAOImpl {
	return &ModelDAOImpl{
		configClient: config.GetClient(),
	}
}

var (
	_               ModelDAO = (*ModelDAOImpl)(nil)
	DefaultModelDAO          = newModelDAOImpl()
)

type ModelsResponse struct {
	Data   []*ModelItem `json:"data"`
	Object string       `json:"object"`
}

const EndAtMs = 1893427200000

func (r *ModelsResponse) IntoModels() []*domainModel.Model {
	if r == nil {
		return nil
	}

	models := make([]*domainModel.Model, 0)

	for _, item := range r.Data {
		priceItem := &domainModel.PriceItem{
			BeginAtMs: 0,
			EndAtMs:   EndAtMs,

			ByInputTokenCount:  item.PriceByInputTokenCount,
			ByOutputTokenCount: item.PriceByOutputTokenCount,
			ByImageCount:       item.PriceByImageCount,
			ByInvocationCount:  0,
			ByTotalTokenQuota:  0,
			ByTotalImageQuota:  0,
		}

		sku := &domainModel.Sku{
			Name:        item.Name,
			DisplayName: item.DisplayName,
			Prices:      []*domainModel.PriceItem{priceItem},
			Model:       nil,
		}

		model := &domainModel.Model{
			Name:          item.Name,
			RPCName:       item.RPCName,
			DisplayName:   item.DisplayName,
			Description:   item.Description,
			OwnerEmail:    item.OwnerEmail,
			Type:          domainModel.ModelType(item.ModelType),
			PlaygroundURL: item.PlaygroundURL,
			Skus:          []*domainModel.Sku{sku},
		}

		sku.Model = model

		models = append(models, model)
	}

	return models
}

type ModelItem struct {
	Created                 int64  `json:"created"`
	Description             string `json:"description"`
	DisplayName             string `json:"display_name"`
	ID                      string `json:"id"`
	IsPublic                bool   `json:"is_public"`
	ModelType               string `json:"model_type"`
	Name                    string `json:"name"`
	Object                  string `json:"object"`
	OwnedBy                 string `json:"owned_by"`
	OwnerEmail              string `json:"owner_email"`
	PlaygroundURL           string `json:"playground_url"`
	PriceByImageCount       int64  `json:"price_by_image_count"`
	PriceByInputTokenCount  int64  `json:"price_by_input_token_count"`
	PriceByOutputTokenCount int64  `json:"price_by_output_token_count"`
	RPCName                 string `json:"rpc_name"`
}

func (d *ModelDAOImpl) ListModels(ctx context.Context) ([]*domainModel.Model, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.dao.ModelDAOImpl.ListModels",
	})

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, macro.ModelProxyUrl+"/models", nil)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to create request")
		return nil, err
	}

	req.Header.Set("Authorization", "Bearer "+macro.ModelProxyAPIKey)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to send request")
		return nil, err
	}

	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		logger.WithField(ctx, "status", resp.StatusCode).Error(ctx, "unexpected status code")
		return nil, errors.New("list models unexpected status code")
	}

	var target ModelsResponse

	decoder := json.NewDecoder(resp.Body)
	err = decoder.Decode(&target)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to unmarshal models")
		return nil, err
	}

	models := target.IntoModels()

	return models, nil
}

func (d *ModelDAOImpl) GetModelByName(ctx context.Context, modelName string) (*domainModel.Model, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "basic.dao.ModelDAOImpl.GetModelByName",
		"modelName": modelName,
	})

	models, err := d.ListModels(ctx)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to list models")
		return nil, err
	}

	for _, model := range models {
		if model.Name == modelName {
			return model, nil
		}
	}
	return nil, nil
}

func (d *ModelDAOImpl) ListSkus(ctx context.Context) (skus []*domainModel.Sku, err error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.dao.ModelDAOImpl.ListSkus",
	})

	models, err := d.ListModels(ctx)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to list models")
		return nil, err
	}
	return lo.Flatten(lo.Map(models, func(model *domainModel.Model, _ int) []*domainModel.Sku {
		return model.Skus
	})), nil
}
