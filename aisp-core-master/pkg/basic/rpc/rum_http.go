package rpc

import (
	"context"
	"strconv"
)

type RumClient[T float32 | float64] interface {
	RumSearch(ctx context.Context, table string, embeddings [][]T, topk int32, query string, fields []string) [][]*SearchResult
	RumUpsert(ctx context.Context, table string, id int64, embedding []T, version string, extras map[string]interface{}) bool
	RumDelete(ctx context.Context, table string, id int64, version string) bool
	RumGet(ctx context.Context, table string, ids []string, fields []string) map[string]any
	RumInfos(ctx context.Context, table string) *RumInfosResponse
}

const UnExistDocId = "-1"

type SearchRequestBody[T float32 | float64] struct {
	Topk       int64    `json:"topk"`
	Embeddings [][]T    `json:"embeddings"`
	Filter     string   `json:"filter,omitempty"`
	Fields     []string `json:"fields,omitempty"`
}

type SearchResult struct {
	Id     string                 `json:"id"`
	Sim    float32                `json:"sim"`
	Fields map[string]interface{} `json:"fields"`
}

type RumGetDetail struct {
	Id        string    `json:"id"`
	Raw       string    `json:"raw"`
	Embedding []float32 `json:"embedding"`
}

// RumUpdateResponse ： 适用更新与删除，返回相同
type RumUpdateResponse struct {
	Succeed   bool     `json:"succeed"`
	FailedMsg []string `json:"failed_msg"`
}

type RumInfosResponse map[string][]*RumInfoDetail

type RumInfoDetail struct {
	Shard   uint32 `json:"shard"`
	Replica uint32 `json:"replica"`
	NTotal  uint64 `json:"ntotal"`
	NList   uint32 `json:"nlist"`
	NProbe  uint32 `json:"nprobe"`
	Filter  bool   `json:"filter"`
}

func (s *SearchResult) GetId() int64 {
	id, _ := strconv.ParseInt(s.Id, 10, 64)
	return id
}
func (s *SearchResult) GetSim() float32 {
	return s.Sim
}

type RumSearchResponse struct {
	Results [][]*SearchResult `json:"results"`
}

func (r *RumSearchResponse) GetResults() [][]*SearchResult {
	return r.Results
}
