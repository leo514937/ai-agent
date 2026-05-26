package rpc

import "context"

type CloudSwayClientRPC interface {
	Search(ctx context.Context, q string, topK int32, extParams map[string]string) ([]*OutSiteSearchRecallAnswerResult, error)
}

type CloudSwayEndpoint string

const (
	CloudSwayBingEndpointSearch  CloudSwayEndpoint = "https://searchapi.xiaosuai.com/LPUqHEAjfonOmohV/bing/v7.0/search"
	CloudSwayQuarkEndpointSearch CloudSwayEndpoint = "https://searchapi.xiaosuai.com/JKkeUNVxgXrDIDcW/bing/v7.0/search"
	CloudSwaySerpEndpointSearch  CloudSwayEndpoint = "https://searchapi.xiaosuai.com/search/NKKfSSdzoosidFhX/serp"
)
