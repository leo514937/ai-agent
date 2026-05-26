package dto

import (
	"context"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	wr "github.com/mroth/weightedrand"
	"github.com/samber/lo"
)

type ModelCapability string

const (
	ModelCapability_Chat          ModelCapability = "chat"
	ModelCapability_StreamChat    ModelCapability = "stream_chat"
	ModelCapability_GenerateImage ModelCapability = "generate_image"
)

type ModelInfo struct {
	Name         string            `json:"name"`
	Capabilities []ModelCapability `json:"capabilities"`
	Endpoints    []*ModelEndpoint  `json:"endpoints"`
}

type ModelEndpoint struct {
	Provider string `json:"provider"`
	Name     string `json:"name"`
	BaseURL  string `json:"base_url"`
	Model    string `json:"model"`
	APIKey   string `json:"api_key"`
	Weight   int32  `json:"weight"`
}

func (m *ModelInfo) ChooseEndpoint(ctx context.Context) *ModelEndpoint {
	endpoints := m.Endpoints

	choices := lo.Map(endpoints, func(item *ModelEndpoint, index int) wr.Choice {
		return wr.Choice{Item: item, Weight: uint(item.Weight)}
	})
	chooser, _ := wr.NewChooser(
		choices...,
	)
	endpoint := chooser.Pick().(*ModelEndpoint)
	StatsdChooseEndpoint(ctx, endpoint)

	return endpoint
}

func StatsdChooseEndpoint(ctx context.Context, endpoint *ModelEndpoint) {
	if endpoint == nil {
		return
	}

	scene := log.GetSceneFromContext(ctx)
	provider := endpoint.Provider
	name := endpoint.Name

	statsd.Increment("aisp-core.scene." + scene + ".model_provider." + provider + ".endpoint." + name + ".count")
}
