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

// go run pkg/portal/mcpclient/zhida/main.go
func main() {
	// 连接到服务器
	serverURL := "http://localhost:8000/api/mcp/zhida/v1/stream"

	// 创建 Streamable HTTP 客户端
	trans, err := transport.NewStreamableHTTP(serverURL, transport.WithHTTPTimeout(5*time.Minute), transport.WithHTTPHeaders(map[string]string{
		"Access-Token": "xxxx", // 替换为你的 Access-Token
	}))
	if err != nil {
		log.Fatalf("创建客户端失败: %v", err)
	}
	defer trans.Close()

	ctx := context.Background()

	// 1. 初始化连接
	fmt.Println("=== 初始化连接 ===")
	initRequest := transport.JSONRPCRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "initialize",
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
	fmt.Println("=== 测试直答请求 ===")

	start := time.Now()

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

	zhidaRequest := transport.JSONRPCRequest{
		JSONRPC: "2.0",
		ID:      2,
		Method:  "tools/call",
		Params: map[string]interface{}{
			"name": "zhida",
			"arguments": map[string]interface{}{
				"query":     "如何看待金价走势？",
				"member_id": 117223006,
			},
		},
	}

	startTime := time.Now()
	zhidaResponse, err := trans.SendRequest(ctx, zhidaRequest)
	if err == nil || err.Error() == "unexpected nil response" {
		fmt.Printf("⏱️  耗时: %v\n", time.Since(startTime))
		fmt.Printf("✅ 请求完成\n")
		if zhidaResponse != nil {
			fmt.Printf("响应: %s\n\n", string(zhidaResponse.Result))
		}
	} else {
		log.Printf("请求失败: %v", err)
	}

	fmt.Println("\n=== 所有测试完成 ===")
	fmt.Println("总耗时:", time.Since(start))
}
