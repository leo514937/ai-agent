package main

import (
	"context"
	"encoding/json"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/samber/lo"
)

func main() {
	var ctx = context.Background()
	query := "aisp-core 这个 app 下有哪些 unit 组? 给出每个 unit 组的描述"

	// 获取部署系统 mcp client
	mcpDeployClient := impl.GetMCPClient("部署系统")
	if mcpDeployClient == nil {
		panic("获取部署系统 mcp client 失败，请检查有没有执行 export ACCESS_TOKEN=登录秘钥（点击云平台左下角头像获取）")
	}

	// 获取所有工具列表
	res, err := mcpDeployClient.ListTools(ctx)
	if err != nil {
		panic(err)
	}

	// 调用 14b 模型选择工具
	callToolRequest := ChooseTools(ctx, util.GetJSONIgnoreError(res), query)
	if callToolRequest == nil {
		fmt.Println("没有选择任何工具")
		return
	}

	// 执行工具调用
	callToolResponse, err := mcpDeployClient.CallTool(ctx, *callToolRequest)
	if err != nil {
		panic(err)
	}

	// 调用 14b 模型生成回答
	summary := Summary(ctx, util.GetJSONIgnoreError(callToolResponse), query)
	fmt.Println("最终回答:\n", summary)
}

func chat(ctx context.Context, aiProfile string, query string) string {
	req := &dto.ChatRequest{
		ModelName: "question-gen-14b",
		AIProfile: aiProfile,
		Messages: []*dto.ChatRequestMessage{{
			Role:    dto.ChatRequestMessageRoleUser,
			Content: query,
		}},
		MaxTokens: lo.ToPtr[int32](4096),
		Stop: []string{
			"<|im_end|>",
			"<|endoftext|>",
		},
		TopP:              lo.ToPtr[float32](0.8),
		Temperature:       lo.ToPtr[float32](0.5),
		PresencePenalty:   lo.ToPtr[float32](0.0),
		FrequencyPenalty:  lo.ToPtr[float32](0.0),
		RepetitionPenalty: lo.ToPtr[float32](1.0),
	}

	response, err := rpc.DefaultModelGatewayRouter.Chat(ctx, req)
	if err != nil || response == nil {
		return ""
	}
	return response.Content
}

func ChooseTools(ctx context.Context, toolsDescription string, query string) *mcp.CallToolRequest {
	aiProfile := fmt.Sprintf("下面有所有工具的描述，请选择一种工具来完成你的任务，返回工具名称和请求参数。\n"+
		"返回结果需要是 json 结构，示例：%s\n 工具描述：%s\n", util.GetJSONIgnoreError(rpc.GetDemoCallToolRequest()), toolsDescription)

	response := chat(ctx, aiProfile, query)

	responseCallToolRequest := &mcp.CallToolRequest{}
	err := json.Unmarshal([]byte(response), responseCallToolRequest)
	if err != nil {
		fmt.Println("解析工具请求参数失败:", err)
		return nil
	}

	return responseCallToolRequest
}

func Summary(ctx context.Context, toolsResponse string, query string) string {
	aiProfile := "你是一个智能助手，下面是执行工具的结果，请根据工具结果回答用户问题：\n" + toolsResponse
	return chat(ctx, aiProfile, query)
}
