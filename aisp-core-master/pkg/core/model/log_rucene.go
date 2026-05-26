package model

var Path = "/rucene/ai/aispcore"
var Index = "batch_aispcore_202410231644"

var LogRuceneMapping = map[string]map[string]any{
	"app_name": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"author_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_keyword1": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_keyword2": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_keyword3": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_long1": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
	"extra_long2": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
	"extra_long3": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
	"graph_name": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"member_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"message_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"query": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"query_seg": {
		"type":          "segmented",
		"index_options": "docs",
		"index":         true,
	},
	"request_info": {
		"type": "keyword",
	},
	"request_time_ms": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
	"resp_message_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"response": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"response_info": {
		"type": "keyword",
	},
	"response_seg": {
		"type":          "segmented",
		"index_options": "docs",
		"index":         true,
	},
	"response_time_ms": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
	"scene": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"client_source": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"traffic_source": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"security": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"service_name": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"session_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"trace_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
}

var LogRuceneSetting = map[string]any{
	"index.provided_name": "code will override this",
	"similarities":        map[string]any{},
}

type LogRucene struct {
	Id                  string      `json:"id"`                     // 唯一id，生成方式为 graphName+"-"+sessionId+"-"+messageId
	MemberId            int64       `json:"member_id"`              // 请求用户id
	Scene               string      `json:"scene"`                  // 场景，例如 DISCOVER_TAB
	GraphName           string      `json:"graph_name"`             // 图名称，例如 stream_chat.DISCOVER_TAB
	SessionId           string      `json:"session_id"`             // 会话id
	RequestTimeMs       int64       `json:"request_time_ms"`        // 请求时间毫秒
	MessageId           string      `json:"message_id"`             // 请求消息 messageId
	Query               string      `json:"query"`                  // 用户输入query
	QuerySeg            SegmentInfo `json:"query_seg"`              // 用户输入query
	ResponseTimeMs      int64       `json:"response_time_ms"`       // 返回时间毫秒
	RespMessageId       string      `json:"resp_message_id"`        // 返回消息 messageId
	Response            []string    `json:"response"`               // 返回结果
	ResponseSeg         SegmentInfo `json:"response_seg"`           // 返回结果
	Security            []string    `json:"security"`               // 安全命中情况
	AuthorId            int64       `json:"author_id"`              // 作者id
	TraceId             string      `json:"trace_id"`               // 后端透传下来的 traceId
	ClientSource        string      `json:"client_source"`          // 客户端来源 0未知 1WEB ...
	TrafficSource       string      `json:"traffic_source"`         // 流量来源 0未知 1直答 2搜索 ...
	RequestInfo         string      `json:"request_info"`           // 请求完整结构体
	ResponseInfo        string      `json:"response_info"`          // 返回完整结构体
	AppName             string      `json:"app_name"`               // app名称
	ServiceName         string      `json:"service_name"`           // 容器组名称
	RequestStartTimeMs  int64       `json:"request_start_time_ms"`  // 请求时间起始毫秒，用于查询
	RequestEndTimeMs    int64       `json:"request_end_time_ms"`    // 请求时间截止毫秒，用于查询
	ResponseStartTimeMs int64       `json:"response_start_time_ms"` // 返回时间起始毫秒，用于查询
	ResponseEndTimeMs   int64       `json:"response_end_time_ms"`   // 返回时间截止毫秒，用于查询
}

func (l *LogRucene) GetResponse() string {
	if len(l.Response) > 0 {
		return l.Response[0]
	}
	return ""
}

type SegmentInfo struct {
	Words   []*Word `json:"words"`
	Raw     string  `json:"raw"`
	Store   bool    `json:"store"`
	Default bool    `json:"default"`
}

type Word struct {
	Value  string `json:"value"`
	Begin  int32  `json:"begin"`
	Length int32  `json:"length"`
}

type SparseWord struct {
	Word  string  `json:"word"`
	Score float32 `json:"score"`
}
