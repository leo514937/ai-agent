package zhida

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	discover_model "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/halo"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/golang/protobuf/jsonpb"
	"github.com/google/uuid"
	"github.com/mark3labs/mcp-go/client/transport"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/samber/lo"
	"go.uber.org/atomic"
)

// 直答 API 响应结构
type ZhidaResponse struct {
	Code      int                `json:"code"`       // 状态码，0表示成功
	Message   string             `json:"message"`    // 状态消息
	RequestID string             `json:"request_id"` // responseMessageId
	Data      *ZhidaResponseData `json:"data"`
}

type ZhidaResponseData struct {
	HasMore         bool            `json:"has_more"`         // 流式过程中为 true，最终结果为 false
	Text            string          `json:"text"`             // 直答模型回答内容
	Thinking        string          `json:"thinking"`         // 思考内容
	RelevantQueries []string        `json:"relevant_queries"` // 相关问题
	References      []ReferenceItem `json:"references"`       // 参考内容列表
}

type ReferenceItem struct {
	Title   string `json:"title"`
	Url     string `json:"url"`
	Snippet string `json:"snippet"`
}

// 工具列表
var Tools = []mcp.Tool{
	{
		Name:        "zhida",
		Description: "知乎直答，用提问发现世界",
		InputSchema: mcp.ToolInputSchema{
			Type: "object",
			Properties: map[string]any{
				"member_id": map[string]any{
					"type":        "number",
					"description": "用户的知乎ID（可选）",
				},
				"query": map[string]any{
					"type":        "string",
					"description": "输入你的问题（长度不超过1万字符）",
				},
			},
			Required: []string{"query"},
		},
	},
}

// Handler 返回流式服务器的 HTTP handler
func ZhidaHandler() http.Handler {
	resources.Init(graph_constant.ApiStreamChat)
	return http.HandlerFunc(handleStreamingChat)
}

// handleStreamingRequest 处理流式请求
func handleStreamingChat(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()

	log.Infof(ctx, "收到请求 RequestURI:%s, Header:%v, Methor:%s", r.RequestURI, r.Header, r.Method)

	accessToken := getAccessTokenFromRequest(r)

	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	log.Infof(ctx, "收到请求: %s %s", r.Method, r.URL.String())

	// 解析请求
	var req transport.JSONRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		log.Error(ctx, "解析请求失败: %v", err)
		http.Error(w, fmt.Sprintf("Invalid JSON: %v", err), http.StatusBadRequest)
		return
	}

	log.Infof(ctx, "处理请求: Request:%s", util.GetJSONIgnoreError(req))

	// 根据不同的方法处理请求
	switch req.Method {
	case string(mcp.MethodInitialize):
		handleInitialize(ctx, w, req)
	case string(mcp.MethodToolsList):
		handleToolsList(ctx, w, req)
	case string(mcp.MethodToolsCall):
		handleToolsCall(ctx, w, req, accessToken)
	default:
		handleUnknownMethod(ctx, w, req)
	}
}

// getAccessTokenFromRequest 从请求头中解析 accessToken。
// 开放平台支持两种鉴权方式：
// 1. 标准版本 Access-Token，通过 AccessID 和 AccessSecret 生成，需要定时刷新，放在 Access-Token 头中传递。
// 2. 简化版本 Bearer，直接使用 AccessSecret，放在 Authorization 头中传递，格式为 Bearer {AccessSecret}。
// 不做强制校验，非法 Access-Token="" ，由下游开放平台返回鉴权错误
// 并保持完整的 Authorization 值（包含 Bearer 前缀）以供下游判断使用 Authorization 还是 Access-Token。
func getAccessTokenFromRequest(r *http.Request) string {
	accessToken := r.Header.Get("Access-Token")
	authHeader := r.Header.Get("Authorization")

	if accessToken != "" {
		return accessToken
	}

	if authHeader != "" {
		if strings.HasPrefix(authHeader, "Bearer ") {
			// 这里保留完整的 Authorization 值（包含 Bearer 前缀），下游根据前缀选择使用 Authorization 还是 Access-Token
			return authHeader
		} else {
			// 要么是 Bearer，要么直接认为是非法格式
			return ""
		}
	}

	return ""
}

func sendErrorResponse(ctx context.Context, w http.ResponseWriter, req transport.JSONRPCRequest, code int, message string) {
	response := transport.JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      &req.ID,
		Error: &struct {
			Code    int             `json:"code"`
			Message string          `json:"message"`
			Data    json.RawMessage `json:"data"`
		}{
			Code:    code,
			Message: message,
		},
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)

	err := json.NewEncoder(w).Encode(response)
	if err != nil {
		log.Infof(ctx, "发送响应失败: %v, id:%d", err, req.ID)
	}
}

func sendJsonResponse(ctx context.Context, w http.ResponseWriter, req transport.JSONRPCRequest, data interface{}, code int) {
	resultData, _ := json.Marshal(data)
	response := transport.JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      &req.ID,
		Result:  resultData,
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)

	err := json.NewEncoder(w).Encode(response)
	if err != nil {
		log.Infof(ctx, "发送响应失败: %v, id:%d", err, req.ID)
	}
}

func sendStreamingResponse(w http.ResponseWriter, zhidaResponse *ZhidaResponse) {
	if zhidaResponse.Data == nil || (zhidaResponse.Data.Thinking == "" && zhidaResponse.Data.Text == "" && len(zhidaResponse.Data.RelevantQueries) == 0 && len(zhidaResponse.Data.References) == 0) {
		// 空响应不发送（阶段开始消息只有状态，没有内容）
		return
	}
	notification := map[string]interface{}{
		"jsonrpc": "2.0",
		"method":  "zhida",
		"params": map[string]interface{}{
			"message": zhidaResponse,
		},
	}
	notificationData, _ := json.Marshal(notification)
	fmt.Fprintf(w, "event: message\n")
	fmt.Fprintf(w, "data: %s\n\n", notificationData)
	w.(http.Flusher).Flush()
}

// handleInitialize 处理初始化请求
func handleInitialize(ctx context.Context, w http.ResponseWriter, req transport.JSONRPCRequest) {
	sendJsonResponse(ctx, w, req, map[string]interface{}{
		"protocolVersion": "2025-10-28",
		"capabilities":    map[string]interface{}{},
		"serverInfo": map[string]interface{}{
			"name":    "Streamable HTTP Server",
			"version": "1.0.0",
		},
	}, http.StatusAccepted)
}

// handleToolsList 处理工具列表请求
func handleToolsList(ctx context.Context, w http.ResponseWriter, req transport.JSONRPCRequest) {
	sendJsonResponse(ctx, w, req, map[string]interface{}{
		"tools": Tools,
	}, http.StatusOK)
}

// handleToolsCall 处理工具调用请求（使用 MCP 标准格式）
func handleToolsCall(ctx context.Context, w http.ResponseWriter, req transport.JSONRPCRequest, accessToken string) {
	// 手动解析 params
	params, ok := req.Params.(map[string]interface{})
	if !ok {
		response := transport.JSONRPCResponse{
			JSONRPC: "2.0",
			ID:      &req.ID,
			Error: &struct {
				Code    int             `json:"code"`
				Message string          `json:"message"`
				Data    json.RawMessage `json:"data"`
			}{
				Code:    mcp.INVALID_PARAMS,
				Message: "Invalid params: params must be an object",
			},
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(response)
		return
	}

	if toolNameValue, ok := params["name"]; ok {
		// 如果有 name 参数，说明是标准的 tools/call 请求
		var toolName string
		if toolNameStr, ok := toolNameValue.(string); ok {
			toolName = toolNameStr
		} else {
			sendErrorResponse(ctx, w, req, mcp.INVALID_PARAMS, "Invalid params: 'name' must be a string")
			return
		}

		// 获取参数
		arguments := map[string]any{}
		if args, ok := params["arguments"].(map[string]any); ok {
			arguments = args
		}
		arguments["access_token"] = accessToken

		// 工具调用
		if toolName == "zhida" {
			handleZhidaTool(ctx, w, req, arguments)
			return
		}

		// 未知工具
		sendErrorResponse(ctx, w, req, mcp.METHOD_NOT_FOUND, fmt.Sprintf("Unknown tool: %s", toolName))
		return
	}

	// 如果没有 name 参数，返回错误
	sendErrorResponse(ctx, w, req, mcp.INVALID_PARAMS, "Invalid params: 'name' is required")
}

// handleUnknownMethod 处理未知方法请求
func handleUnknownMethod(ctx context.Context, w http.ResponseWriter, req transport.JSONRPCRequest) {
	sendErrorResponse(ctx, w, req, mcp.METHOD_NOT_FOUND, fmt.Sprintf("Method not found: %s", req.Method))
}

// handleZhidaTool 处理 zhida 工具的流式响应
func handleZhidaTool(ctx context.Context, w http.ResponseWriter, req transport.JSONRPCRequest, params map[string]any) {
	// 设置 SSE 响应头
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.WriteHeader(http.StatusOK)

	// 获取参数
	query, ok := params["query"].(string)
	if !ok {
		sendStreamingResponse(w, &ZhidaResponse{
			Code:    -1,
			Message: "Invalid params: 'query' is required and must be a string",
		})
		return
	}

	memberId, ok := params["member_id"].(int64)
	if !ok {
		memberId = 0
	}

	accessToken := params["access_token"].(string)

	zhidaRequest := genZhidaRequest(ctx, query, memberId)
	response := StreamChatWithMCP(ctx, zhidaRequest, accessToken, w)
	if response.Data == nil {
		response.Data = &ZhidaResponseData{}
	}
	response.Data.HasMore = false

	// 发送最终的流式响应给客户端
	sendStreamingResponse(w, response)
	// 发送最终的非流式响应给客户端
	sendJsonResponse(ctx, w, req, response, http.StatusOK)

	log.Infof(ctx, "Zhida mcp tool call completed, request:%s, response:%s", util.GetJSONIgnoreError(zhidaRequest), util.GetJSONIgnoreError(response))
}

func genZhidaRequest(ctx context.Context, query string, memberId int64) *proto.ChatRequest {
	return &proto.ChatRequest{
		Type: proto.ChatType_ZHIDA_MCP,
		Info: &proto.RequestInfo{
			Message: &proto.ChatMessage{
				MessageId:   util.Int64String(int64(uuid.New().ID())),
				TimestampMs: util.TimeUnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        query,
			},
			MemberId: memberId,
		},
		RespMessageId: util.Int64String(int64(uuid.New().ID())),
		Header: &proto.RequestHeader{
			ClientSource:  proto.ClientSource_PC_WEB,
			TrafficSource: proto.TrafficSource_zhida,
			Version:       "v2",
		},
	}
}

func chatResponseToResponse(req *proto.ChatRequest, resp *proto.ChatResponse, err error) *ZhidaResponse {
	if err != nil {
		return &ZhidaResponse{
			Code:      -1,
			Message:   err.Error(),
			RequestID: resp.GetMessage().GetMessageId(),
		}
	}

	var relevantQueries []string
	for _, queryItem := range resp.GetRelevantQueries() {
		relevantQueries = append(relevantQueries, queryItem.GetQuery())
	}

	var references []ReferenceItem
	for _, card := range resp.GetCards() {
		// 前置检查：确保是 ZhihuRelevantSource 类型
		if zhihuSource, ok := card.GetCardContent().(*proto.ChatCard_ZhidaRelevantSource); ok {
			references = append(references, ReferenceItem{
				Title:   zhihuSource.ZhidaRelevantSource.GetDocTitle(),
				Url:     zhihuSource.ZhidaRelevantSource.GetDocId(),
				Snippet: zhihuSource.ZhidaRelevantSource.GetDocAbstract(),
			})
		}
	}

	return &ZhidaResponse{
		Code:      0,
		Message:   "success",
		RequestID: req.RespMessageId,
		Data: &ZhidaResponseData{
			HasMore:         resp.State == proto.ChatState_PROCESSING,
			Text:            resp.GetMessage().GetText(),
			Thinking:        resp.GetThink(),
			RelevantQueries: relevantQueries,
			References:      references,
		},
	}
}

func makePlatFormRequest(ctx context.Context, zhidaRequest *proto.ChatRequest, accessToken string) (*http.Request, error) {
	// 创建 http 请求
	params := url.Values{}
	params.Set("Query", zhidaRequest.GetInfo().GetMessage().GetText())
	params.Set("SceneType", util.Int64String(int64(zhidaRequest.GetType())))
	requestURL := "http://platform.zhihu.com/api/v1/content/zhida?" + params.Encode()
	req, err := http.NewRequestWithContext(ctx, "GET", requestURL, nil) // 使用 WithContext 传递 context

	if err != nil {
		return nil, err
	}

	// 设置请求头
	req.Header.Set("Accept", "text/event-stream")
	req.Header.Set("Cache-Control", "no-cache")
	// 兼容两种开放平台鉴权方式：
	// 1. 通过 Access-Token 头进行鉴权
	// 2. 通过 Bearer + X-Request-Timestamp 的方式进行鉴权
	if accessToken != "" {
		if strings.HasPrefix(accessToken, "Bearer ") {
			// Bearer 方式：accessToken 本身就是完整的 Authorization 值
			req.Header.Set("Content-Type", "application/json")
			req.Header.Set("Authorization", accessToken)
			req.Header.Set("X-Request-Timestamp", strconv.FormatInt(time.Now().Unix(), 10))
		} else {
			// Access-Token 方式：直接透传
			req.Header.Set("Access-Token", accessToken)
		}
	}

	return req, nil
}

type PlatformResponse struct {
	Code    int             `json:"Code"`    // 注意：JSON字段名是大写
	Message string          `json:"Message"` // 注意：JSON字段名是大写
	Data    json.RawMessage `json:"Data"`    // 使用 RawMessage 延迟解析
}

// StreamChatWithMCP 调用开放平台直答接口并处理流式响应
func StreamChatWithMCP(ctx context.Context, zhidaRequest *proto.ChatRequest, accessToken string, w http.ResponseWriter) *ZhidaResponse {

	logger := log.WithField(ctx, "StreamChat.Request", zhidaRequest)
	logger.Infof(ctx, "Start, RequestParams:%v", util.GetJSONIgnoreError(zhidaRequest))

	chatErrResp := &proto.ChatResponse{
		State:        proto.ChatState_CANCELED,
		Message:      &proto.ChatMessage{MessageId: zhidaRequest.RespMessageId},
		ReqSessionId: zhidaRequest.GetInfo().GetSessionId(),
	}

	// 创建调用开放平台直答接口的 http 请求
	platFormRequest, err := makePlatFormRequest(ctx, zhidaRequest, accessToken)
	if err != nil {
		logger.Errorf(ctx, "makePlatFormRequest error : %v", err)
		return chatResponseToResponse(zhidaRequest, chatErrResp, err)
	}

	// 发送请求
	client := &http.Client{Timeout: 600 * time.Second}
	resp, err := client.Do(platFormRequest)
	if err != nil {
		logger.Errorf(ctx, "http client do error : %v", err)
		return chatResponseToResponse(zhidaRequest, chatErrResp, err)
	}

	defer func() {
		err := resp.Body.Close()
		if err != nil {
			logger.Errorf(ctx, "close response body error : %v", err)
		}
	}()

	// 检查响应状态
	if resp.StatusCode != http.StatusOK {
		logger.Errorf(ctx, "response status code error : %d", resp.StatusCode)
		return chatResponseToResponse(zhidaRequest, chatErrResp, errors.New(fmt.Sprintf("响应状态码错误: %d", resp.StatusCode)))
	}

	// 读取SSE流
	lastResp := &ZhidaResponse{}
	scanner := bufio.NewScanner(resp.Body)
	for scanner.Scan() {
		line := scanner.Text()

		// 如果收到[DONE]标记，结束读取
		if strings.Contains(line, "[DONE]") {
			logger.Infof(ctx, "收到结束标记，停止读取")
			break
		}

		if line == ": keep-alive" {
			// 心跳包，忽略
			continue
		}

		line = strings.TrimPrefix(line, "data: ")
		if line == "" {
			continue
		}

		// 先解析外层包装结构
		platformResp := &PlatformResponse{}
		err := json.Unmarshal([]byte(line), platformResp)
		if err != nil {
			logger.Errorf(ctx, "json unmarshal error : %v, line:%s", err, line)
			continue
		}

		// 检查 Code 是否为成功
		if platformResp.Code != 0 {
			logger.Errorf(ctx, "platform response error, code: %d, message: %s", platformResp.Code, platformResp.Message)
			lastResp = &ZhidaResponse{
				Code:      platformResp.Code,
				Message:   platformResp.Message,
				RequestID: zhidaRequest.RespMessageId,
			}
			break
		}

		// 检查 Data 是否存在
		if len(platformResp.Data) == 0 {
			logger.Errorf(ctx, "platform response data is empty")
			continue
		}

		// 解析 Data，构建 ZhidaResponse 结构体
		chatResp, err := platformDataToChatResponse(ctx, platformResp.Data, logger)
		if err != nil {
			logger.Errorf(ctx, "platformDataToChatResponse error : %v", err)
			continue
		}
		lastResp = chatResponseToResponse(zhidaRequest, chatResp, nil)

		// 发送流式响应给客户端
		sendStreamingResponse(w, lastResp)
	}

	if err := scanner.Err(); err != nil {
		// 检查是否是 context 取消导致的错误
		select {
		case <-ctx.Done():
			logger.Infof(ctx, "客户端主动断开连接: %v", ctx.Err())
			return lastResp
		default:
			logger.Errorf(ctx, "读取响应失败: %v", err)
			return chatResponseToResponse(zhidaRequest, chatErrResp, err)
		}
	}

	return lastResp
}

func platformDataToChatResponse(ctx context.Context, data json.RawMessage, logger *log.ZhihuLogger) (*proto.ChatResponse, error) {
	chatResp := &proto.ChatResponse{}

	// 先解析为 map，提取 cards 字段
	var dataMap map[string]interface{}
	if err := json.Unmarshal(data, &dataMap); err != nil {
		logger.Errorf(ctx, "json unmarshal data map error : %v", err)
		return chatResp, err
	}

	// 使用 jsonpb 反序列化其他字段
	unmarshaler := &jsonpb.Unmarshaler{
		AllowUnknownFields: true, // 允许未知字段
	}
	err := unmarshaler.Unmarshal(bytes.NewReader(data), chatResp)
	if err != nil {
		logger.Errorf(ctx, "jsonpb unmarshal error : %v, data: %s", err, string(data))
		return chatResp, err
	}

	// 单独处理 cards 字段，使用对应的 protobuf 结构体反序列化
	cardsRaw, cardsExists := dataMap["cards"]
	if cardsExists && cardsRaw != nil {
		if cardsArray, ok := cardsRaw.([]interface{}); ok {
			convertedCards := make([]*proto.ChatCard, 0, len(cardsArray))
			for _, cardRaw := range cardsArray {
				if cardMap, ok := cardRaw.(map[string]interface{}); ok {
					// 处理 CardContent oneof 字段
					if cardContentRaw, ok := cardMap["CardContent"].(map[string]interface{}); ok {
						chatCard := &proto.ChatCard{}

						// 处理 ZhidaRelevantSource -> ChatCardProRelevantSource
						if zhidaSourceRaw, ok := cardContentRaw["ZhidaRelevantSource"].(map[string]interface{}); ok {
							// 直接序列化原始数据，jsonpb 会自动处理字段名转换
							zhidaSourceJSON, _ := json.Marshal(zhidaSourceRaw)
							zhidaSource := &proto.ChatCardProRelevantSource{}
							if err := unmarshaler.Unmarshal(bytes.NewReader(zhidaSourceJSON), zhidaSource); err == nil {
								chatCard.CardContent = &proto.ChatCard_ZhidaRelevantSource{
									ZhidaRelevantSource: zhidaSource,
								}
							} else {
								logger.Errorf(ctx, "unmarshal ZhidaRelevantSource error : %v", err)
							}
						}

						// 处理 ZhihuRelevantSource -> ChatCardZhihuRelevantSource
						if zhihuSourceRaw, ok := cardContentRaw["ZhihuRelevantSource"].(map[string]interface{}); ok {
							// 直接序列化原始数据，jsonpb 会自动处理字段名转换
							zhihuSourceJSON, _ := json.Marshal(zhihuSourceRaw)
							zhihuSource := &proto.ChatCardZhihuRelevantSource{}
							if err := unmarshaler.Unmarshal(bytes.NewReader(zhihuSourceJSON), zhihuSource); err == nil {
								chatCard.CardContent = &proto.ChatCard_ZhihuRelevantSource{
									ZhihuRelevantSource: zhihuSource,
								}
							} else {
								logger.Errorf(ctx, "unmarshal ZhihuRelevantSource error : %v", err)
							}
						}

						// 处理 OtherRelevantSource -> ChatCardOtherRelevantSource
						if otherSourceRaw, ok := cardContentRaw["OtherRelevantSource"].(map[string]interface{}); ok {
							// 直接序列化原始数据，jsonpb 会自动处理字段名转换
							otherSourceJSON, _ := json.Marshal(otherSourceRaw)
							otherSource := &proto.ChatCardOtherRelevantSource{}
							if err := unmarshaler.Unmarshal(bytes.NewReader(otherSourceJSON), otherSource); err == nil {
								chatCard.CardContent = &proto.ChatCard_OtherRelevantSource{
									OtherRelevantSource: otherSource,
								}
							} else {
								logger.Errorf(ctx, "unmarshal OtherRelevantSource error : %v", err)
							}
						}

						// 如果成功解析了 CardContent，添加到 cards 列表
						if chatCard.CardContent != nil {
							convertedCards = append(convertedCards, chatCard)
						}
					}
				}
			}
			// 填充 cards 到 ChatResponse
			chatResp.Cards = convertedCards
		}
	}

	return chatResp, nil
}

// StreamChatWithMCPInternal 走的直答内部调用，没有通过开放平台转发，无法计费，用于自测
func StreamChatWithMCPInternal(ctx context.Context, zhidaRequest *proto.ChatRequest, w http.ResponseWriter) *ZhidaResponse {

	logger := log.WithField(ctx, "StreamChat.Request", zhidaRequest)
	logger.Infof(ctx, "Start, RequestParams:%v", util.GetJSONIgnoreError(zhidaRequest))

	// 初始化graph上下文
	_, stageConfig := getConfigMap(zhidaRequest)
	bizRequestContext := entities.NewRequestContextFromChatRequestAndStageConf(zhidaRequest, stageConfig)

	// 初始化 productContext
	bizRequestContext.SetProductContext(discover_model.NewDiscoverTabContext(zhidaRequest))

	haloFTSpan := halo.NewHalo(ctx, "AISP_AispChatService_StreamChat_FirstToken", zhidaRequest.GetType().String())
	clientSourceSpan := halo.NewHalo(ctx, "AISP_AispChatService_StreamChat_ClientSource",
		fmt.Sprintf("%s_%s", zhidaRequest.GetType().String(), bizRequestContext.GetClientSource().String()))
	trafficSourceSpan := halo.NewHalo(ctx, "AISP_AispChatService_StreamChat_TrafficSource",
		fmt.Sprintf("%s_%s", zhidaRequest.GetType().String(), bizRequestContext.GetTrafficSource().String()))
	nowTime := time.Now()

	waitFirstToken := atomic.NewBool(true)

	defer func() {
		clientSourceSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		trafficSourceSpan.EndWithContext(ctx, time.Since(nowTime), nil)
	}()

	logger.Infof(ctx, "graph.RunGraph Start")

	itemList, _, _, err := graph.RunGraphByCallback(ctx, bizRequestContext, nil, func(eventData *chat_event.EventInfo) {
		// 首Token bds 打点
		if waitFirstToken.Load() && (eventData.GetCurrEventType() == chat_event.ThinkEventType || eventData.GetCurrEventType() == chat_event.AnswerEventType) {
			text := ""
			if len(eventData.GetThinkContent()) > 0 {
				text = eventData.GetThinkContent()
			}
			if eventData.GetCurrEventType() == chat_event.AnswerEventType && eventData.GetAnswerContent() != nil {
				text = eventData.GetAnswerContent().Content
			}

			if text != "" &&
				text != generate.ThinkingMessage &&
				text != generate.GetDeepThinkingMessage() &&
				text != generate.GetRetryMessage() {
				haloFTSpan.EndWithContext(ctx, time.Since(nowTime), nil)
				waitFirstToken.Store(false)
			}
		}

		// 发送流式相应给客户端
		chatResp := bizRequestContext.GetChatEventResponseHandler().Transition(eventData, nil)
		resp := chatResponseToResponse(zhidaRequest, chatResp, nil)

		sendStreamingResponse(w, resp)
	})

	// 异常情况处理
	if err != nil || len(itemList) == 0 {
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "graph failed")
		} else {
			log.Infof(ctx, "AispChatService.StreamChat itemList is empty")
		}
		chatResp := &proto.ChatResponse{
			State:        proto.ChatState_CANCELED,
			Message:      nil,
			ReqSessionId: zhidaRequest.GetInfo().GetSessionId(),
		}
		resp := chatResponseToResponse(zhidaRequest, chatResp, err)

		return resp
	}
	logger.Infof(ctx, "graph.RunGraph Done")

	// 处理最终响应
	allEventData := bizRequestContext.GetChatEvent().GetAllEventData()
	lastResp := bizRequestContext.GetChatEventResponseHandler().TransitionSource(allEventData, true, nil)

	// 构建最终响应
	if res, isExist := lo.First[*entities.Item](itemList); isExist {
		// 安全检查
		answerRefusedBySecurity := !res.GetSecurity().IsSecurityAllPassed()
		if answerRefusedBySecurity {
			log.Infof(ctx, "security is not passed res: %s ", util.GetJSONIgnoreError(res))
		}

		// 填充内容
		lastResp.Think = res.Think
		lastResp.Message = res.ToChatMessage()
		if res.ChatRespType != proto.ChatRespType_UNKNOWN_RESP {
			lastResp.RespType = res.ChatRespType
		}
		resp := chatResponseToResponse(zhidaRequest, lastResp, nil)

		logger.Infof(ctx, "========> Final response. resp: %s", util.GetJSONIgnoreError(resp))

		return resp
	} else {
		logger.WithError(ctx, err).Warnf(ctx, "itemList first item is empty!")
		resp := chatResponseToResponse(zhidaRequest, lastResp, errors.New("response empty"))

		return resp
	}
}

func getConfigMap(request *proto.ChatRequest) (map[string]map[string]string, stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item]) {
	//  优先匹配新版 获取当前图配置
	graphStageLogicConfig, isExistStageConfig := stage_handler.GetGraphStageConfig(stage_handler.BuildGraphLogicConfigName(graph_constant.ApiStreamChat, request.GetType().String()))
	if !isExistStageConfig {
		// 获取当前图配置
		graphLogicConfig, isExist := conf.GetGraphConfig(conf.BuildLogicConfigName(graph_constant.ApiStreamChat, request.GetType().String()))
		if !isExist {
			return map[string]map[string]string{}, nil
		}
		return graphLogicConfig.GetBizConfigMap(), nil
	}
	return graphStageLogicConfig.GetDefaultBizConfigMap(), graphStageLogicConfig
}
