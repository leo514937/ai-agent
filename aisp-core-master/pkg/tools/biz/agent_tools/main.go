package main

import (
	"context"
	"flag"
	"fmt"
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/agent_tool"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router/sub_graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router/tools"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

func main() {

	var (
		text string
	)
	flag.StringVar(&text, "text", "hello world", "user input query")
	flag.Parse()

	ctx := context.Background()

	// 模拟创建reqCtx
	reqCtx := entities.NewRequestContextFromChatRequest(&proto.ChatRequest{
		Header: &proto.RequestHeader{
			TrafficSource: proto.TrafficSource_zhida,
			ClientSource:  proto.ClientSource_PC_WEB,
		},
		Type:          proto.ChatType_ZHIDA_AGENT,
		RespMessageId: "11111",
		Info: &proto.RequestInfo{
			SessionId: "11111",
			MemberId:  246248568,
			Message: &proto.ChatMessage{
				Type:      proto.ChatMessageType_TEXT,
				MessageId: "11111",
				Text:      "介绍一下知乎直答",
			},
		},
	}, make(map[string]map[string]string))
	reqCtx.InitChatEvent(func(eventDate *chat_event.EventInfo) {

	})

	requestContext := data_frame.NewRequestContext[entities.RequestContext, entities.User, entities.Item]()
	requestContext.SetBizContext(reqCtx)

	service := sub_graph.NewDirectChatSubService()

	// 创建Tools
	profileTool := tools.NewProfileTool(requestContext.GetBizContext(), service)
	clarifyTool := tools.NewClarifyTool(requestContext.GetBizContext(), service)
	jailbreakTool := tools.NewJailbreakTool(requestContext.GetBizContext(), service)
	directReplyTool := tools.NewDirectReplyTool(requestContext.GetBizContext(), service)
	researchTool := tools.NewResearchTool(requestContext.GetBizContext(), service)
	// 创建ToolMap
	toolMap := make(map[string]agent_tool.IAgentTool)
	toolMap[profileTool.GetName()] = profileTool
	toolMap[clarifyTool.GetName()] = clarifyTool
	toolMap[jailbreakTool.GetName()] = jailbreakTool
	toolMap[directReplyTool.GetName()] = directReplyTool
	toolMap[researchTool.GetName()] = researchTool
	// 注册验证器
	toolCallValidator := agent_tool.NewToolCallValidator()
	toolCallValidator.RegisterTool(profileTool.GetName(), profileTool.GetParameters())
	toolCallValidator.RegisterTool(clarifyTool.GetName(), clarifyTool.GetParameters())
	toolCallValidator.RegisterTool(jailbreakTool.GetName(), jailbreakTool.GetParameters())
	toolCallValidator.RegisterTool(directReplyTool.GetName(), directReplyTool.GetParameters())
	toolCallValidator.RegisterTool(researchTool.GetName(), researchTool.GetParameters())

	// 最大尝试3次 调用tool
	retryMaxCount := 3
	for i := range retryMaxCount {
		functionToolCall, valid := doRouter(ctx, toolMap, toolCallValidator, text)
		if valid {
			if tool, isExist := toolMap[functionToolCall.Name]; isExist {
				tool.Run(ctx, functionToolCall)
			}
			break
		}
		fmt.Printf("重试中......%d\n", i+1)
	}

	fmt.Println("done...")
}

func doRouter(ctx context.Context, toolMap map[string]agent_tool.IAgentTool, toolCallValidator *agent_tool.ToolCallValidator, query string) (dto.FunctionCallResult, bool) {
	// 创建ToolsList（用于提交给模型）
	toolList := lo.MapToSlice(toolMap, func(key string, value agent_tool.IAgentTool) dto.Tool {
		return value.ToFunction()
	})

	// 调用模型并校验
	modelGatewayRPC := rpc.DefaultModelGatewayRouter
	messages := []*dto.ChatRequestMessage{
		{
			Role: dto.ChatRequestMessageRoleSystem,
			Content: `你是知乎直答内前置的路由助手。Based on the user's request, select the most appropriate reply tool.
Note: You can only select one tool.

以下是知乎直答的介绍：
## 产品介绍：
1. 产品名称：知乎直答
2. 产品研发方：知乎
3. 所属国家：中国
4. 底座模型：知乎直答是基于知海图AI大模型、DeepSeek-R1 等模型等开发的产品，知海图大模型是由知乎和面壁智能联合开发的大型语言模型，与任何其他组织或个人无关；
5. 产品简介：知乎直答是一款高效、易用、可信的 AI 搜索工具，为用户提供以知乎内容为中心，多种数据源作为补充的优质回答内容；
6. 能力范围：能够基于大模型强大的语义理解和生成能力，准确地理解用户的问题，快速地从知乎平台大量优质内容中检索信息，为用户准确和深入地回答各种领域的问题，包括但不限于科学、技术、文学、历史、军事等；还可以为用户提供日常生活中的建议，如出游、饮食、运动等；也能够基于用户的需求生成创意内容，如故事、诗歌、文章等，提供灵感和结构化建议，激发用户的创造力；支持多种编程语言（Python、C++、Java 等），能写代码、优化代码、找 bug 并提供解释；支持流畅的语言翻译，并能进行文本润色和语法纠正；能够解决数学问题，并提供详细的推导过程。
7. 暂时不支持的功能：根据url链接获取内容、图片生成、文件生成。`,
		},
		{
			Role:    dto.ChatRequestMessageRoleUser,
			Content: query,
		},
	}

	// 构建 ChatRequest
	chatRequest := &dto.ChatRequest{
		ModelName: "zhida-doubao-seed-1-6",
		Messages:  messages,
		Tools:     toolList,
		ExtraBody: map[string]interface{}{
			"thinking": map[string]string{"type": "disabled"},
		},
	}

	// 调用 Responses 接口
	response, err := modelGatewayRPC.Responses(ctx, chatRequest)
	if err != nil || response == nil || !strings.HasPrefix(response.ResponseId, "resp_") {
		fmt.Printf("ModelGatewayRPC.Responses failed: %v\n", err)
		return dto.FunctionCallResult{}, false
	}

	for _, functionCall := range response.FunctionCallResults {
		fmt.Printf("验证数据......%s => args:%s\n", functionCall.Name, functionCall.Arguments)
		if functionCall.Name != "" {
			validateResult := toolCallValidator.ValidateToolCall(functionCall.Name, functionCall.Arguments)
			if validateResult.Valid {
				return functionCall, true
			}
		}
	}
	return dto.FunctionCallResult{}, false
}
