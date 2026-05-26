package model

import "github.com/samber/lo"

type Model struct {
	Name          string    `json:"name"`
	RPCName       string    `json:"rpc_name"`
	DisplayName   string    `json:"display_name"`
	Description   string    `json:"description"`
	OwnerEmail    string    `json:"owner_email"`
	Type          ModelType `json:"type"`
	PlaygroundURL string    `json:"playground_url"`
	Skus          []*Sku    `json:"skus"`
}

func (m *Model) GetRPCName() string {
	result, _ := lo.Coalesce(m.RPCName, m.Name)
	return result
}

type PriceItem struct {
	BeginAtMs int64 `json:"begin_at_ms"`
	EndAtMs   int64 `json:"end_at_ms"`

	ByInputTokenCount  int64 `json:"by_input_token_count"`
	ByOutputTokenCount int64 `json:"by_output_token_count"`
	ByImageCount       int64 `json:"by_image_count"`
	ByInvocationCount  int64 `json:"by_invocation"`
	ByTotalTokenQuota  int64 `json:"by_total_token_quota"`
	ByTotalImageQuota  int64 `json:"by_total_image_quota"`
}

type ModelType string

const (
	ModelTypeChat            ModelType = "CHAT"
	ModelTypeEmbedding       ModelType = "EMBEDDING"
	ModelTypeImageGeneration ModelType = "IMAGE_GENERATION"
)

type Sku struct {
	Name        string       `json:"name"`
	DisplayName string       `json:"display_name"`
	Prices      []*PriceItem `json:"prices"`
	Model       *Model       `json:"model"`
}
