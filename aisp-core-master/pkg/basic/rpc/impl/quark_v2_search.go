package impl

import (
	"context"
	"encoding/json"
	"net/http"

	config2 "git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	openapi "github.com/alibabacloud-go/darabonba-openapi/v2/client"
	iqsClient "github.com/alibabacloud-go/iqs-20241111/client"
	util "github.com/alibabacloud-go/tea-utils/v2/service"
	"github.com/samber/lo"
)

const (
	timeoutMillSecondsV2 = 5000
	timeRangeDefaultV2   = "NoLimit"
)

// QuarkSearchV2RPCImpl 接口文档见：https://help.aliyun.com/document_detail/2857020.html#a70f5e3a53osy
type QuarkSearchV2RPCImpl struct {
	client *iqsClient.Client
}

func NewQuarkSearchV2RPC() rpc.QuarkSearchRPC {
	configStr := config2.GetString("quark_search", "")
	if configStr == "" {
		panic("quark_search config is empty")
	}

	var quarkSearchConfig quarkSearchV2Config
	err := json.Unmarshal([]byte(configStr), &quarkSearchConfig)

	config := &openapi.Config{
		AccessKeyId:     lo.ToPtr(quarkSearchConfig.AccessKeyId),
		AccessKeySecret: lo.ToPtr(quarkSearchConfig.AccessKeySecret),
		Endpoint:        lo.ToPtr(quarkSearchConfig.EndpointV2),
		ReadTimeout:     lo.ToPtr(timeoutMillSecondsV2),
	}

	client, err := iqsClient.NewClient(config)
	if err != nil {
		log.Errorf(context.Background(), "new quark search client failed, %v", err)
	}

	return &QuarkSearchV2RPCImpl{
		client: client,
	}
}

func (q *QuarkSearchV2RPCImpl) Search(ctx context.Context, query string, topK int32, traceId string) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	logger := log.WithField(ctx, "QuarkSearch", query)
	results := make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
	request := &iqsClient.GenericSearchRequest{
		Query:     lo.ToPtr(query),
		SessionId: lo.ToPtr(traceId),
		TimeRange: lo.ToPtr(timeRangeDefaultV2),
	}
	runtime := &util.RuntimeOptions{}

	var err error
	var resp *iqsClient.GenericSearchResponse
	runFunc := func(ctx context.Context) error {
		resp, err = q.client.GenericSearchWithOptions(request, nil, runtime)
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	if err != nil {
		logger.Warnf(ctx, "query from linked_retrieval failed, query:%s, error:%v", query, err)
		return results, err
	}
	if resp == nil {
		logger.Warnf(ctx, "response is nil, query:%s", query)
		return results, nil
	}
	if lo.FromPtr(resp.StatusCode) != http.StatusOK || resp.Body == nil {
		logger.Warnf(ctx, "response.body is nil or status not ok, query:%s, status:%d", query, lo.FromPtr(resp.StatusCode))
		return results, nil
	}

	for _, pageItem := range resp.Body.PageItems {
		snippet := lo.FromPtr(pageItem.HtmlSnippet)
		mainText := lo.FromPtr(pageItem.MainText)
		result := rpc.OutSiteSearchRecallAnswerResult{
			Name:          lo.FromPtr(pageItem.Title),
			Url:           lo.FromPtr(pageItem.Link),
			Snippet:       snippet,
			MainText:      mainText,
			PublishedTime: lo.FromPtr(pageItem.PublishTime) / 1000,
		}
		results = append(results, &result)
	}
	// 由于夸克搜索暂时还不能指定召回数量 所以这里先暂时做后limit限制
	return results[:zrecUtil.Min(int(topK), len(results))], nil
}

type quarkSearchV2Config struct {
	Endpoint        string `json:"endpoint"`
	EndpointV2      string `json:"endpoint_v2"`
	AccessKeyId     string `json:"access_key_id"`
	AccessKeySecret string `json:"access_key_secret"`
}
