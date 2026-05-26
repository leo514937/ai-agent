package modelapi

import (
	"context"
	"sync"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type ModelProvider interface {
	ProviderNames() []string
	Target(model *dto.ModelEndpoint) ModelTarget
}

type ModelRouter struct {
	registry sync.Map
}

var DefaultModelRouter *ModelRouter = NewModelRouter()

func NewModelRouter() *ModelRouter {
	return &ModelRouter{}
}

func (r *ModelRouter) Register(provider ModelProvider) {
	for _, name := range provider.ProviderNames() {
		r.registry.Store(name, provider)
		log.Infof(context.Background(), "Register ok. name: %s provider: %+v ", name, provider)
	}
}

func (r *ModelRouter) GetModelTarget(ctx context.Context, model *dto.ModelInfo) ModelTarget {
	log.Infof(ctx, "GetModelTarget start. model: %+v ", model)
	endpoint := model.ChooseEndpoint(ctx)
	log.Infof(ctx, "ChooseEndpoint ok. modelInfoName:%s endpoint: %+v ", model.Name, endpoint)

	providerAny, isOk := r.registry.Load(endpoint.Provider)
	if !isOk {
		log.Errorf(ctx, "registry.Load not ok. endpoint: %+v ", endpoint)
		return nil
	}

	log.Infof(ctx, "registry.Load ok. providerAny: %+v ", providerAny)

	provider, isOk := providerAny.(ModelProvider)
	if !isOk {
		log.Errorf(ctx, "providerAny.(ModelProvider) not ok. providerAny: %+v ", providerAny)
		return nil
	}
	log.Infof(ctx, "providerAny.(ModelProvider) ok. provider: %+v ", provider)

	return provider.Target(endpoint)
}

func (r *ModelRouter) GetModelProxyTarget(ctx context.Context, modelName string) ModelTarget {
	endpoints := []*dto.ModelEndpoint{
		&dto.ModelEndpoint{
			Provider: "vllm-openai",
			Name:     modelName,
			BaseURL:  macro.ModelProxyUrl,
			Model:    modelName,
			APIKey:   "app-aisp-core",
			Weight:   1,
		},
	}
	newModel := &dto.ModelInfo{Name: modelName, Endpoints: endpoints}
	return r.GetModelTarget(ctx, newModel)
}
