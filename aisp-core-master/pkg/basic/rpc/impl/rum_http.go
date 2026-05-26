package impl

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config/config_struct"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
)

type RumClientImpl[T float32 | float64] struct {
	rumClient *http.Client
	rumConfig *config_struct.RumConfig
}

var DefaultFloat64RumClientImpl rpc.RumClient[float64]
var DefaultFloat32RumClientImpl rpc.RumClient[float32]

func init() {
	DefaultFloat64RumClientImpl = NewRumClientImpl[float64](conf.GetRumConfig(), conf.GetRumConfig().TimeoutDefault)
	DefaultFloat32RumClientImpl = NewRumClientImpl[float32](conf.GetRumConfig(), conf.GetRumConfig().TimeoutDefault)
}

func NewRumClientImpl[T float32 | float64](searchConfig *config_struct.RumConfig, timeoutMilli int64) *RumClientImpl[T] {
	if timeoutMilli == 0 {
		timeoutMilli = searchConfig.TimeoutDefault
	}

	return &RumClientImpl[T]{
		rumConfig: searchConfig,
		rumClient: &http.Client{Timeout: time.Duration(timeoutMilli) * time.Millisecond},
	}
}

// RumSearch & RumSearchWithFilter https://wiki.in.zhihu.com/display/TeamSearch/search
func (s *RumClientImpl[T]) RumSearch(ctx context.Context, table string, embeddings [][]T, topk int32, query string, fields []string) [][]*rpc.SearchResult {
	response := &rpc.RumSearchResponse{}
	var result [][]*rpc.SearchResult

	runFunc := func(ctx context.Context) error {
		params := url.Values{}
		params.Set("table", table)

		urlSt := &url.URL{
			Scheme:   s.rumConfig.Scheme,
			Host:     s.rumConfig.SearthHost,
			Path:     s.rumConfig.SearchPath,
			RawQuery: params.Encode(),
		}
		requestBody := rpc.SearchRequestBody[T]{
			Topk:       int64(topk),
			Embeddings: embeddings,
			Filter:     query,
			Fields:     fields,
		}
		requestBodyStr, _ := json.Marshal(requestBody)

		req, err := http.NewRequestWithContext(ctx, http.MethodPost, urlSt.String(), bytes.NewBuffer(requestBodyStr))
		if err != nil {
			return err
		}

		req.Header.Add("content-type", "application/json")
		resp, err := s.rumClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("rum serach failed, status=%d", resp.StatusCode)
		} else {
			body, err := io.ReadAll(resp.Body)
			if err != nil {
				return err
			}

			err = json.Unmarshal(body, response)
			if err != nil {
				return err
			}
		}

		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	if response == nil || len(response.GetResults()) == 0 {
		return result
	}

	// 清洗数据，去除 -1
	for _, itemList := range response.GetResults() {
		resultList := []*rpc.SearchResult{}
		for _, item := range itemList {
			if item.Id == rpc.UnExistDocId {
				continue
			}
			resultList = append(resultList, item)
		}
		result = append(result, resultList)
	}

	return result
}

// RumUpsert https://wiki.in.zhihu.com/display/TeamSearch/upsert
func (s *RumClientImpl[T]) RumUpsert(ctx context.Context, table string, id int64, embedding []T, version string, extras map[string]interface{}) bool {
	result := &rpc.RumUpdateResponse{}

	runFunc := func(ctx context.Context) error {
		params := url.Values{}
		params.Set("table", table)

		// 默认为最新版本
		if version != "" {
			params.Set("version", version)
		}
		urlSt := &url.URL{
			Scheme:   s.rumConfig.Scheme,
			Host:     s.rumConfig.UpdateHost,
			Path:     s.rumConfig.UpsertPath,
			RawQuery: params.Encode(),
		}

		requestBody := map[string]interface{}{}
		requestBody["id"] = util.Int64ToStr(id)
		embeddingFloat64, isFloat64 := any(embedding).([]float64)
		if isFloat64 {
			requestBody["embedding"] = util.Float64SliceToFloat32(embeddingFloat64)
		} else {
			requestBody["embedding"] = embedding
		}

		for k, v := range extras {
			requestBody[k] = v
		}

		requestBodyStr, _ := json.Marshal(requestBody)

		req, err := http.NewRequestWithContext(ctx, http.MethodPost, urlSt.String(), bytes.NewBuffer(requestBodyStr))
		if err != nil {
			return err
		}

		req.Header.Add("content-type", "application/json")
		resp, err := s.rumClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("rum upsert failed, status=%d", resp.StatusCode)
		} else {
			body, err := io.ReadAll(resp.Body)
			if err != nil {
				return err
			}
			err = json.Unmarshal(body, result)
			if err != nil {
				return err
			}
		}

		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result.Succeed
}

// RumDelete https://wiki.in.zhihu.com/display/TeamSearch/delete
func (s *RumClientImpl[T]) RumDelete(ctx context.Context, table string, id int64, version string) bool {
	result := &rpc.RumUpdateResponse{}

	runFunc := func(ctx context.Context) error {
		params := url.Values{}
		params.Set("table", table)
		params.Set("id", util.Int64ToStr(id))

		// 默认为最新版本
		if version != "" {
			params.Set("version", version)
		}
		urlSt := &url.URL{
			Scheme:   s.rumConfig.Scheme,
			Host:     s.rumConfig.UpdateHost,
			Path:     s.rumConfig.DeletePath,
			RawQuery: params.Encode(),
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodDelete, urlSt.String(), http.NoBody)
		if err != nil {
			return err
		}

		req.Header.Add("content-type", "application/json")
		resp, err := s.rumClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()

		// 删除时 404 也认为删除成功
		if resp.StatusCode == http.StatusNotFound {
			return nil
		}

		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("rum delete failed, status=%d", resp.StatusCode)
		} else {
			body, err := io.ReadAll(resp.Body)
			if err != nil {
				return err
			}
			err = json.Unmarshal(body, result)
			if err != nil {
				return err
			}
		}

		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result.Succeed
}

// RumGet https://wiki.in.zhihu.com/display/TeamSearch/get
func (s *RumClientImpl[T]) RumGet(ctx context.Context, table string, ids []string, fields []string) map[string]any {
	var result = make(map[string]any)

	runFunc := func(ctx context.Context) error {
		params := url.Values{}
		params.Set("table", table)
		params.Set("ids", strings.Join(ids, ","))
		params.Set("fields", strings.Join(fields, ","))

		urlSt := &url.URL{
			Scheme:   s.rumConfig.Scheme,
			Host:     s.rumConfig.GetHost,
			Path:     s.rumConfig.GetPath,
			RawQuery: params.Encode(),
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodGet, urlSt.String(), http.NoBody)
		if err != nil {
			return err
		}

		req.Header.Add("content-type", "application/json")
		resp, err := s.rumClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("rum get failed, status=%d", resp.StatusCode)
		} else {
			body, err := io.ReadAll(resp.Body)
			if err != nil {
				return err
			}

			err = json.Unmarshal(body, &result)
			if err != nil {
				return err
			}
		}

		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

// RumInfos https://wiki.in.zhihu.com/display/TeamSearch/infos
func (s *RumClientImpl[T]) RumInfos(ctx context.Context, table string) *rpc.RumInfosResponse {
	result := &rpc.RumInfosResponse{}

	runFunc := func(ctx context.Context) error {
		params := url.Values{}
		params.Set("table", table)

		urlSt := &url.URL{
			Scheme:   s.rumConfig.Scheme,
			Host:     s.rumConfig.SearthHost,
			Path:     s.rumConfig.InfosPath,
			RawQuery: params.Encode(),
		}

		req, err := http.NewRequestWithContext(ctx, http.MethodGet, urlSt.String(), http.NoBody)
		if err != nil {
			return err
		}

		req.Header.Add("content-type", "application/json")
		resp, err := s.rumClient.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("rum infos failed, status=%d", resp.StatusCode)
		} else {
			body, err := io.ReadAll(resp.Body)
			if err != nil {
				return err
			}
			err = json.Unmarshal(body, result)
			if err != nil {
				return err
			}
		}

		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

//var _ rpc.RumClient = (*RumClientImpl)(nil)
