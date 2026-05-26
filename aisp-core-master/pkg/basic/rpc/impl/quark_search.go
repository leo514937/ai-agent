package impl

import (
	"context"
	"encoding/json"
	"io"

	config2 "git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	openapi "github.com/alibabacloud-go/darabonba-openapi/v2/client"
	openapiutil "github.com/alibabacloud-go/openapi-util/service"
	util "github.com/alibabacloud-go/tea-utils/v2/service"
	"github.com/alibabacloud-go/tea/tea"
)

const (
	pathName           = "/linked-retrieval/linked-retrieval-entry/v2/linkedRetrieval/commands/aiSearch"
	timeoutMillSeconds = 5000
	timeRangeDefault   = "NoLimit"
)

// QuarkSearchRPCImpl 接口文档见：https://help.aliyun.com/document_detail/2837802.html?spm=a2c4g.11186623.help-menu-2837261.d_1_1.402f2473rnk9Gz&scm=20140722.H_2837802._.OR_help-V_1
type QuarkSearchRPCImpl struct {
	client *openapi.Client
}

var DefaultQuarkSearchClient = NewQuarkSearchRPC()

func NewQuarkSearchRPC() rpc.QuarkSearchRPC {
	configStr := config2.GetString("quark_search", "")
	if configStr == "" {
		panic("quark_search config is empty")
	}

	var quarkSearchConfig quarkSearchConfig
	err := json.Unmarshal([]byte(configStr), &quarkSearchConfig)

	config := &openapi.Config{
		AccessKeyId:     tea.String(quarkSearchConfig.AccessKeyId),
		AccessKeySecret: tea.String(quarkSearchConfig.AccessKeySecret),
		Endpoint:        tea.String(quarkSearchConfig.Endpoint),
		ReadTimeout:     tea.Int(timeoutMillSeconds),
	}
	client, err := openapi.NewClient(config)
	if err != nil {
		log.Errorf(context.Background(), "new quark search client failed, %v", err)
	}

	return &QuarkSearchRPCImpl{
		client: client,
	}
}

func (q *QuarkSearchRPCImpl) Search(ctx context.Context, query string, topK int32, traceId string) ([]*rpc.OutSiteSearchRecallAnswerResult, error) {
	timeRange := timeRangeDefault
	// query 超出提前截断
	if util2.UnicodeLen(query) > 100 {
		log.Warnf(ctx, "quark search query is too long, max length is 100, current length is %d", util2.UnicodeLen(query))
		query = util2.UnicodeSubstr(query, 0, 100)
	}
	events, err := q.doSseQuery(query, &traceId, &timeRange)
	if err != nil {
		log.Warnf(ctx, "query from linked_retrieval failed, %v", err)
		return []*rpc.OutSiteSearchRecallAnswerResult{}, err
	}

	var results = make([]*rpc.OutSiteSearchRecallAnswerResult, 0)
	for event := range events {
		var eventData eventData
		err := json.Unmarshal([]byte(*event.Data), &eventData)
		if err != nil {
			log.Warnf(ctx, "quark event data json unmarshal failed, %v", err)
			return []*rpc.OutSiteSearchRecallAnswerResult{}, err
		}

		// 请求RequestId, 排查问题时可以提供此信息
		requestId := eventData.RequestID

		// 当前的eventName，支持: on_common_search_end, on_post_retrieval_end 两种事件，可以根据需要选择
		eventName := eventData.Header.Event

		// 服务端当前Event的时延(从服务端接收到请求开始)
		serverRT := eventData.Header.ResponseTime

		// 具体消息的内容，参考文档说明: 内部是一个JSON，
		payload := eventData.Payload

		log.Infof(ctx, "quark search [%s] %s serverRt:%d, \n\n", requestId, eventName, serverRT)

		searchResponseItems := make([]searchResponseItem, 0)
		if eventName == "on_post_retrieval_end" {
			log.Infof(ctx, "quark search [%s] %s serverRt:%d, payload:%s \n\n", requestId, eventName, serverRT, payload)

			err = json.Unmarshal([]byte(payload), &searchResponseItems)
			if err != nil {
				log.Warnf(ctx, "quark payload json unmarshal failed, %v", err)
				return nil, err
			}

			for _, searchResponseItem := range searchResponseItems {
				metaData := searchResponseItem.MetaData
				result := rpc.OutSiteSearchRecallAnswerResult{
					Name:          metaData.Title,
					Url:           metaData.Link,
					Snippet:       metaData.HtmlSnippet,
					PublishedTime: metaData.PublishTime / 1000,
					MainText:      metaData.MainText,
				}
				results = append(results, &result)
			}
		}

	}

	// 由于夸克搜索暂时还不能指定召回数量 所以这里先暂时做后limit限制
	return results[:zrecUtil.Min(int(topK), len(results))], nil
}

func createApiInfo() *openapi.Params {
	params := &openapi.Params{
		// 接口名称
		Action: tea.String("AISearchV2"),
		// 接口版本
		Version: tea.String("2024-05-01"),
		// 接口协议
		Protocol: tea.String("HTTPS"),
		// 接口 HTTP 方法
		Method:   tea.String("GET"),
		AuthType: tea.String("AK"),
		Style:    tea.String("ROA"),
		// 接口 PATH
		Pathname: tea.String(pathName),
		// 接口请求体内容格式
		ReqBodyType: tea.String("json"),
		// 接口响应体内容格式，注意一定得是binary格式，CallApi才会透传出response body进行ReadAsSSE
		BodyType: tea.String("binary"),
	}
	return params
}

func (q *QuarkSearchRPCImpl) doSseQuery(query string, sessionId *string, timeRange *string) (<-chan util.SSEEvent, error) {
	params := createApiInfo()
	// query params
	queries := map[string]interface{}{
		"query":     tea.String(query),
		"sessionId": tea.StringValue(sessionId),
		"timeRange": tea.StringValue(timeRange),
	}

	// runtime options
	runtime := &util.RuntimeOptions{}
	request := &openapi.OpenApiRequest{
		Query: openapiutil.Query(queries),
	}
	// 复制代码运行请自行打印 API 的返回值
	// 返回值为 Map 类型，可从 Map 中获得三类数据：响应体 body、响应头 headers、HTTP 返回的状态码 statusCode。
	resp, err := q.client.CallApi(params, request, runtime)
	if err != nil {
		return nil, err
	}

	// 迭代读取SSE内容
	events, sseErrors := util.ReadAsSSE(resp["body"].(io.ReadCloser))

	select {
	case sseError := <-sseErrors:
		err = sseError
	default:
		// 没有错误的情况
		err = nil
	}
	return events, err
}

type eventData struct {
	Payload   string `json:"payload"`
	RequestID string `json:"requestId"`
	Header    header `json:"header"`
}

type header struct {
	EventID      string `json:"eventId"`
	ResponseTime int    `json:"responseTime"`
	Event        string `json:"event"`
}

type pageMetaData struct {
	CardType    string `json:"card_type"`
	Title       string `json:"title"`
	HtmlTitle   string `json:"html_title"`
	Link        string `json:"link"`
	DisplayLink string `json:"display_link"`
	HtmlSnippet string `json:"html_snippet"`
	PublishTime int64  `json:"publish_time"`
	MainText    string `json:"main_text"`
}

type quarkSearchConfig struct {
	Endpoint        string `json:"endpoint"`
	AccessKeyId     string `json:"access_key_id"`
	AccessKeySecret string `json:"access_key_secret"`
}

type searchResponseItem struct {
	Id       string       `json:"id"`
	MetaData pageMetaData `json:"metadata"`
}
