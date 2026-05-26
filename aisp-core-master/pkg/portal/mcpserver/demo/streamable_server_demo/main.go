package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/mark3labs/mcp-go/client/transport"
	"github.com/mark3labs/mcp-go/mcp"
)

// 工具列表
var Tools = []mcp.Tool{
	{
		Name:        "echo_stream",
		Description: "流式发送回声消息，可以指定消息内容和发送数量",
		InputSchema: mcp.ToolInputSchema{
			Type: "object",
			Properties: map[string]any{
				"message": map[string]any{
					"type":        "string",
					"description": "要发送的消息内容",
				},
				"count": map[string]any{
					"type":        "number",
					"description": "要发送的消息数量",
					"minimum":     1,
					"maximum":     100,
				},
			},
			Required: []string{"message", "count"},
		},
	},
}

// go run pkg/portal/mcpserver/demo/streamable_server_demo/main.go
func main() {
	// 注册流式消息处理器
	http.HandleFunc("/stream", handleStreamingRequest)

	// 健康检查端点
	http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("OK"))
	})

	log.Println("Streamable HTTP Server 启动在 :8080")
	log.Println("流式端点: http://localhost:8080/stream")
	log.Println("健康检查: http://localhost:8080/health")

	// 启动服务器
	if err := http.ListenAndServe(":8080", nil); err != nil {
		log.Fatalf("服务器启动失败: %v", err)
	}
}

// handleStreamingRequest 处理流式请求
func handleStreamingRequest(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	log.Printf("收到请求: %s %s", r.Method, r.URL.String())

	// 解析请求
	var req transport.JSONRPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		log.Printf("解析请求失败: %v", err)
		http.Error(w, fmt.Sprintf("Invalid JSON: %v", err), http.StatusBadRequest)
		return
	}

	log.Printf("处理请求: Method=%s, ID=%d", req.Method, req.ID)

	// 根据不同的方法处理请求
	switch req.Method {
	case string(mcp.MethodInitialize):
		handleInitialize(w, req)
	case string(mcp.MethodToolsList):
		handleToolsList(w, req)
	case string(mcp.MethodToolsCall):
		handleToolsCall(w, req)
	default:
		handleUnknownMethod(w, req)
	}
}

// handleInitialize 处理初始化请求
func handleInitialize(w http.ResponseWriter, req transport.JSONRPCRequest) {
	// 设置响应头
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusAccepted)

	// 发送响应
	resultData, _ := json.Marshal(map[string]interface{}{
		"protocolVersion": "2025-03-26",
		"capabilities":    map[string]interface{}{},
		"serverInfo": map[string]interface{}{
			"name":    "Streamable HTTP Server",
			"version": "1.0.0",
		},
	})

	response := transport.JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      &req.ID,
		Result:  resultData,
	}

	if err := json.NewEncoder(w).Encode(response); err != nil {
		log.Printf("发送响应失败: %v", err)
	}
}

// handleToolsList 处理工具列表请求
func handleToolsList(w http.ResponseWriter, req transport.JSONRPCRequest) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)

	resultData, _ := json.Marshal(map[string]interface{}{
		"tools": Tools,
	})

	response := transport.JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      &req.ID,
		Result:  resultData,
	}

	if err := json.NewEncoder(w).Encode(response); err != nil {
		log.Printf("发送响应失败: %v", err)
	}
}

// handleToolsCall 处理工具调用请求（使用 MCP 标准格式）
func handleToolsCall(w http.ResponseWriter, req transport.JSONRPCRequest) {
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
			response := transport.JSONRPCResponse{
				JSONRPC: "2.0",
				ID:      &req.ID,
				Error: &struct {
					Code    int             `json:"code"`
					Message string          `json:"message"`
					Data    json.RawMessage `json:"data"`
				}{
					Code:    mcp.INVALID_PARAMS,
					Message: "Invalid params: 'name' must be a string",
				},
			}
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			json.NewEncoder(w).Encode(response)
			return
		}

		// 获取参数
		arguments := map[string]any{}
		if args, ok := params["arguments"].(map[string]any); ok {
			arguments = args
		}

		// 工具调用
		if toolName == "echo_stream" {
			handleEchoStreamTool(w, req, arguments)
			return
		}

		// 未知工具
		response := transport.JSONRPCResponse{
			JSONRPC: "2.0",
			ID:      &req.ID,
			Error: &struct {
				Code    int             `json:"code"`
				Message string          `json:"message"`
				Data    json.RawMessage `json:"data"`
			}{
				Code:    mcp.METHOD_NOT_FOUND,
				Message: fmt.Sprintf("Unknown tool: %s", toolName),
			},
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(response)
		return
	}

	// 如果没有 name 参数，返回错误
	response := transport.JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      &req.ID,
		Error: &struct {
			Code    int             `json:"code"`
			Message string          `json:"message"`
			Data    json.RawMessage `json:"data"`
		}{
			Code:    mcp.INVALID_PARAMS,
			Message: "Invalid params: 'name' is required",
		},
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(response)
}

// handleEchoStreamTool 处理 echo_stream 工具的流式响应
func handleEchoStreamTool(w http.ResponseWriter, req transport.JSONRPCRequest, params map[string]any) {
	// 设置 SSE 响应头
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.WriteHeader(http.StatusOK)

	// 获取参数
	message, ok := params["message"].(string)
	if !ok {
		message = "Hello, MCP Streaming!"
	}

	count := 5
	if cnt, ok := params["count"].(float64); ok {
		count = int(cnt)
	}

	log.Printf("开始流式发送: %s, 数量: %d", message, count)

	// 获取 Flusher 接口
	flusher, ok := w.(http.Flusher)
	if !ok {
		log.Printf("ResponseWriter 不支持 Flush")
		return
	}

	// 发送多个流式通知
	for i := 1; i <= count; i++ {
		// 检查客户端连接状态
		select {
		case <-w.(http.CloseNotifier).CloseNotify():
			log.Printf("客户端连接已断开，停止发送")
			return
		default:
		}

		// 发送进度通知
		notification := map[string]interface{}{
			"jsonrpc": "2.0",
			"method":  "echo/progress",
			"params": map[string]interface{}{
				"message":   message,
				"index":     i,
				"total":     count,
				"progress":  float64(i) / float64(count) * 100,
				"timestamp": time.Now().Unix(),
			},
		}
		notificationData, _ := json.Marshal(notification)

		// 写入数据并检查错误
		if _, err := fmt.Fprintf(w, "event: message\n"); err != nil {
			log.Printf("写入事件头失败: %v", err)
			return
		}
		if _, err := fmt.Fprintf(w, "data: %s\n\n", notificationData); err != nil {
			log.Printf("写入数据失败: %v", err)
			return
		}

		// 刷新缓冲区并检查错误
		flusher.Flush()

		log.Printf("发送进度通知: %d/%d", i, count)

		// 使用更短的延迟，避免超时
		time.Sleep(1 * time.Second)
	}

	// 发送最终响应
	finalResultData, _ := json.Marshal(map[string]interface{}{
		"message":     message,
		"totalSent":   count,
		"status":      "completed",
		"completedAt": time.Now().Unix(),
	})

	finalResponse := transport.JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      &req.ID,
		Result:  finalResultData,
	}
	responseData, _ := json.Marshal(finalResponse)

	// 写入最终响应并检查错误
	if _, err := fmt.Fprintf(w, "event: message\n"); err != nil {
		log.Printf("写入最终事件头失败: %v", err)
		return
	}
	if _, err := fmt.Fprintf(w, "data: %s\n\n", responseData); err != nil {
		log.Printf("写入最终数据失败: %v", err)
		return
	}

	flusher.Flush()

	log.Printf("流式消息发送完成，共发送 %d 条消息", count)
}

// handleUnknownMethod 处理未知方法
func handleUnknownMethod(w http.ResponseWriter, req transport.JSONRPCRequest) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)

	response := transport.JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      &req.ID,
		Error: &struct {
			Code    int             `json:"code"`
			Message string          `json:"message"`
			Data    json.RawMessage `json:"data"`
		}{
			Code:    mcp.METHOD_NOT_FOUND,
			Message: fmt.Sprintf("Method not found: %s", req.Method),
		},
	}

	if err := json.NewEncoder(w).Encode(response); err != nil {
		log.Printf("发送响应失败: %v", err)
	}
}
