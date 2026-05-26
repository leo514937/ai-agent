package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"time"

	"github.com/mark3labs/mcp-go/client/transport"
	"github.com/mark3labs/mcp-go/mcp"
)

// go run pkg/portal/mcpserver/demo/streamable_client_demo/main.go
func main() {

	ctx := context.Background()

	// 连接到服务器
	serverURL := "http://localhost:8080/stream"

	// 创建 Streamable HTTP 客户端时设置更长的超时
	trans, err := transport.NewStreamableHTTP(serverURL, transport.WithHTTPTimeout(5*time.Minute))
	if err != nil {
		log.Fatalf("创建客户端失败: %v", err)
	}
	defer trans.Close()

	// 1. 初始化连接
	fmt.Println("=== 初始化连接 ===")
	initRequest := transport.JSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "initialize",
		Params: map[string]interface{}{
			"protocolVersion": "2025-03-26",
			"capabilities":    map[string]interface{}{},
			"clientInfo": map[string]interface{}{
				"name":    "Streamable HTTP Client",
				"version": "1.0.0",
			},
		},
	}

	initResponse, err := trans.SendRequest(ctx, initRequest)
	if err != nil {
		log.Fatalf("初始化失败: %v", err)
	}

	fmt.Printf("✅ 初始化成功\n")
	fmt.Printf("响应: %s\n\n", string(initResponse.Result))

	// 查询工具列表
	fmt.Println("=== 查询工具列表 ===")
	toolsListRequest := transport.JSONRPCRequest{
		JSONRPC: "2.0",
		ID:      2,
		Method:  "tools/list",
	}

	toolsListResponse, err := trans.SendRequest(ctx, toolsListRequest)
	if err != nil {
		log.Printf("获取工具列表失败: %v", err)
	} else {
		fmt.Printf("✅ 获取到工具列表\n\n")
		// 解析工具列表为 mcp.ListToolsResult
		var result mcp.ListToolsResult
		if err := json.Unmarshal(toolsListResponse.Result, &result); err == nil {
			for i, tool := range result.Tools {
				fmt.Printf("工具 %d:\n", i+1)
				fmt.Printf("  名称: %s\n", tool.Name)
				fmt.Printf("  描述: %s\n", tool.Description)
				fmt.Printf("  参数:\n")
				if tool.InputSchema.Properties != nil {
					for paramName, paramInfo := range tool.InputSchema.Properties {
						if paramMap, ok := paramInfo.(map[string]any); ok {
							paramType := paramMap["type"]
							paramDesc := paramMap["description"]
							fmt.Printf("    - %s (%v): %v\n", paramName, paramType, paramDesc)
						}
					}
				}
				fmt.Println()
			}
		} else {
			log.Printf("解析工具列表失败: %v", err)
		}
	}

	// 测试调用工具
	fmt.Println("=== 测试调用工具 ===")

	// 设置通知处理器
	trans.SetNotificationHandler(func(notification mcp.JSONRPCNotification) {
		// 提取方法和参数
		method := notification.Method
		params := notification.Params.AdditionalFields

		fmt.Printf("📢 收到通知: %s\n", method)
		if params != nil {
			paramsJSON, _ := json.MarshalIndent(params, "", "  ")
			fmt.Printf("参数: %s\n\n", string(paramsJSON))
		}
	})

	//  测试回声流式请求
	fmt.Println("=== 测试回声流式请求 ===")
	echoRequest := transport.JSONRPCRequest{
		JSONRPC: "2.0",
		ID:      2,
		Method:  "tools/call",
		Params: map[string]interface{}{
			"name": "echo_stream",
			"arguments": map[string]interface{}{
				"message": "Hello, Streamable HTTP!",
				"count":   20,
			},
		},
	}

	startTime := time.Now()
	echoResponse, err := trans.SendRequest(ctx, echoRequest)
	if err != nil {
		log.Printf("发送请求失败: %v", err)
	} else {
		fmt.Printf("⏱️  耗时: %v\n", time.Since(startTime))
		fmt.Printf("✅ 请求完成\n")
		fmt.Printf("响应: %s\n\n", string(echoResponse.Result))
	}

	fmt.Println("\n=== 所有测试完成 ===")
}
