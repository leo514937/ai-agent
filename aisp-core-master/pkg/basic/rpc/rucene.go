package rpc

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/ioutil"
	"net"
	"net/http"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
)

type RuceneServiceRPC interface {
	Search(ctx context.Context, host string, path string, index string, param *client.SearchQueryRequest) (*client.Response, error)
	// 覆盖模式，保存最新版本 https://wiki.in.zhihu.com/pages/viewpage.action?pageId=170560305
	Add(ctx context.Context, host string, path string, index string, doc interface{}, uniqueKey string) error
	AddWithRetry(ctx context.Context, host string, path string, index string, doc interface{}, uniqueKey string) error
	Delete(ctx context.Context, host string, path string, index string, doc interface{}, uniqueKey string) error
	BuildNewIndex(ctx context.Context, path string, index string, mappings map[string]map[string]any, settings map[string]any) error
	OpenLogIndex(ctx context.Context, path string, index string) error
	RemoveDocWithQuery(ctx context.Context, host string, path string, index string, param client.Query) error
}

type RuceneServiceRPCImpl struct {
	raw           *http.Client
	offlineClient *http.Client
}

var DefaultRuceneServiceRPC RuceneServiceRPC

func init() {
	DefaultRuceneServiceRPC = NewRuceneServiceRPC(500 * time.Millisecond)
}

func NewRuceneServiceRPC(timeout time.Duration) *RuceneServiceRPCImpl {
	offlineClient := &http.Client{
		Transport: &http.Transport{
			DialContext: (&net.Dialer{
				KeepAlive: 30 * time.Second,
			}).DialContext,
			MaxIdleConns:          10240,
			MaxIdleConnsPerHost:   1024,
			IdleConnTimeout:       5 * time.Second,
			TLSHandshakeTimeout:   1 * time.Second,
			ExpectContinueTimeout: 1 * time.Second,
		},
	}
	offlineClient.Timeout = time.Duration(3) * time.Minute
	return &RuceneServiceRPCImpl{
		raw: &http.Client{
			Timeout: timeout,
		},
		offlineClient: offlineClient,
	}
}

type Segmented struct {
	Store   bool   `json:"store,omitempty"`   // 是否存储raw，缺省false
	Default bool   `json:"default,omitempty"` // words为空时是否使用默认 jieba 分词，缺省false。此处需要传 true
	Raw     string `json:"raw,omitempty"`     // 原始内容
}

type RuceneRpcModel struct {
	Description Segmented `json:"description"`
	Name        string    `json:"name"`
	DocID       string    `json:"doc_id"`
	Tags        []string  `json:"tags"`
	ImageToken  string    `json:"image_token"`
	State       string    `json:"state"`
	Created     int64     `json:"created_at"`
}

func (r *RuceneServiceRPCImpl) BuildNewIndex(ctx context.Context, path string, index string, mappings map[string]map[string]any, settings map[string]any) error {
	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	url := ruceneHost + "/create_index?path=" + path
	params := "index=" + index

	metaMap := make(map[string]any)
	metaIndexMap := make(map[string]any)
	metaIndexMap["mappings"] = mappings
	settings["index.provided_name"] = index
	metaIndexMap["settings"] = settings
	metaMap[index] = metaIndexMap
	metaStr, _ := json.Marshal(metaMap)

	params += "&meta=" + string(metaStr)
	bytesData := []byte(params)

	log.Infof(ctx, "url:%s,param:%s", url, params)
	req, err := http.NewRequest("POST", url, bytes.NewReader(bytesData))
	resp, err := r.offlineClient.Do(req)
	res, err := ioutil.ReadAll(resp.Body)
	log.Infof(ctx, "resp.Body:%s,err:%v", res, err)
	if err != nil {
		log.Errorf(ctx, "Build new index error, path:%s, index:%s err:%+v", path, index, err)
	}

	return err
}

func (r *RuceneServiceRPCImpl) OpenLogIndex(ctx context.Context, path string, index string) error {
	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	url := ruceneHost + "/open_index?path=" + path
	params := "index=" + index
	bytesData := []byte(params)

	req, err := http.NewRequest("POST", url, bytes.NewReader(bytesData))
	resp, err := r.offlineClient.Do(req)
	_, err = ioutil.ReadAll(resp.Body)

	if err != nil {
		log.Errorf(ctx, "open index error, path:%s, index:%s err:%+v", path, index, err)
	}

	return err
}

func (r *RuceneServiceRPCImpl) Search(ctx context.Context, host string, path string, index string, param *client.SearchQueryRequest) (*client.Response, error) {
	requestURL := fmt.Sprintf("%s/search?path=%s&index=%s", host, path, index)
	searchMeta, err := json.Marshal(param)
	if err != nil {
		return nil, err
	}

	response, err := r.raw.Post(requestURL, "application/json", strings.NewReader(string(searchMeta))) // nolint:noctx
	if err != nil {
		return nil, err
	}
	defer func() {
		if err = response.Body.Close(); err != nil {
			log.Errorf(ctx, "Search response body close error, path:%s, err:%+v", path, err)
		}
	}()

	if response.StatusCode != http.StatusOK {
		log.Errorf(ctx, "Search error, rucenePath:%s, statusCode:%d", path, response.StatusCode)
		return nil, errors.New("request rucene failed")
	}

	bodyBytes, err := ioutil.ReadAll(response.Body)
	if err != nil {
		return nil, err
	}
	log.Infof(ctx, "Search response index:%s, searchMeta=%s, bodyBytes size:%d", index, string(searchMeta), len(bodyBytes))

	var searchResp *client.Response
	if err = json.Unmarshal(bodyBytes, &searchResp); err != nil {
		return nil, err
	}

	if searchResp.Total == 0 {
		log.Infof(ctx, "Rucene return no data, request param:%s", string(searchMeta))
	}

	return searchResp, nil
}

func (r *RuceneServiceRPCImpl) RemoveDocWithQuery(ctx context.Context, host string, path string, index string, param client.Query) error {
	requestURL := fmt.Sprintf("%s/remove_doc?path=%s&index=%s", host, path, index)
	queryParam, err := json.Marshal(param)
	if err != nil {
		return err
	}

	response, err := r.raw.Post(requestURL, "application/json", strings.NewReader(string(queryParam))) // nolint:noctx
	if err != nil || response == nil {
		return err
	}
	defer func() {
		if err = response.Body.Close(); err != nil {
			log.Errorf(ctx, "Remove doc response body close error, path:%s, err:%+v", path, err)
		}
	}()

	if response.StatusCode != http.StatusOK {
		log.Errorf(ctx, "Remove doc error, rucenePath:%s, statusCode:%d", path, response.StatusCode)
		return errors.New("request rucene failed")
	}

	return nil
}

// 在 Add 基础上加 3 次 retry
func (r *RuceneServiceRPCImpl) AddWithRetry(ctx context.Context, host string, path string, index string, doc interface{}, uniqueKey string) error {
	retryCount := 3
	var err error
	for i := 0; i < retryCount; i++ {
		err = r.Add(ctx, host, path, index, doc, uniqueKey)
		if err == nil {
			return nil
		}
		log.Errorf(ctx, "RuceneServiceRPCImpl AddWithRetry failed, attempt %d/%d, err: %v", i+1, retryCount, err)
	}
	return fmt.Errorf("failed to add document after %d attempts: %w", retryCount, err)
}

func (r *RuceneServiceRPCImpl) Add(ctx context.Context, host string, path string, index string, doc interface{}, uniqueKey string) error {
	err := r.doWrite(ctx, host, path, index, doc, "add", uniqueKey)
	if err != nil {
		return err
	}
	return err
}

func (r *RuceneServiceRPCImpl) Delete(ctx context.Context, host string, path string, index string, doc interface{}, uniqueKey string) error {
	err := r.doWrite(ctx, host, path, index, doc, "delete", uniqueKey)
	if err != nil {
		return err
	}

	return err
}

func (r *RuceneServiceRPCImpl) doWrite(ctx context.Context, host string, path string, index string, doc interface{}, method string, uniqueKey string) error {
	docMarshal, err := json.Marshal(doc)
	if err != nil {
		fmt.Println(fmt.Sprintf("marshal index err:%v", err))
		return err
	}

	requestURL := fmt.Sprintf("%s/add_doc?escape=false&path=%s&index=%s&method=%s", host, path, index, method)

	if uniqueKey != "" {
		requestURL += "&key=" + uniqueKey
	}

	req, err := http.NewRequest("POST", requestURL, bytes.NewReader(docMarshal)) // nolint:noctx
	if err != nil {
		log.Errorf(ctx, "Rucene http.NewRequest error, req:%+v, err:%+v", req, err)
		return err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Add("X-S4-Compatible", "true")
	if method == "delete" || method == "add" || method == "update" {
		log.Infof(ctx, "requestURL: %s, docData: %v", requestURL, string(docMarshal))
	}
	response, err := r.raw.Do(req)
	if err != nil {
		log.Errorf(ctx, "Rucene raw.Do error, req:%+v, err:%+v", req, err)
		return err
	}

	defer func() {
		if err = response.Body.Close(); err != nil {
			log.Errorf(ctx, "Rucene doWrite response body close error, path:%s, err:%+v", path, err)
		}
	}()

	if response.StatusCode != http.StatusOK {
		log.Errorf(ctx, "Rucene doWrite error, rucenePath:%s, statusCode:%d", path, response.StatusCode)
		return errors.New("request rucene failed")
	}
	return err
}
