package provider

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	http2 "net/http"
	"strings"
	"sync"
	"time"

	"git.in.zhihu.com/go/base/http"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/klara_meta/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/klara_meta/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/halo"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/Azure/azure-sdk-for-go/sdk/ai/azopenai"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/to"
	"github.com/golang-jwt/jwt"
	"github.com/openai/openai-go/v2"
	"github.com/openai/openai-go/v2/option"
	"github.com/openai/openai-go/v2/packages/param"
	"github.com/openai/openai-go/v2/responses"
	"github.com/openai/openai-go/v2/shared/constant"
	"github.com/samber/lo"
)

// 全局 HTTP 客户端单例，用于连接复用
var (
	globalHTTPClient *http2.Client
	httpClientOnce   sync.Once
)

// getGlobalHTTPClient 获取全局 HTTP 客户端单例
func getGlobalHTTPClient() *http2.Client {
	httpClientOnce.Do(func() {
		globalHTTPClient = util.NewHttpClient("POST", "", 15*time.Minute).GetHttpClient()
	})
	return globalHTTPClient
}

type OpenAIProvider struct {
}

var (
	_ modelapi.ModelProvider = (*OpenAIProvider)(nil)
)

func init() {
	modelapi.DefaultModelRouter.Register(NewOpenAIProvider())
}

func NewOpenAIProvider() *OpenAIProvider {
	return &OpenAIProvider{}
}

func (p *OpenAIProvider) ProviderNames() []string {
	return []string{"openai", "azure-openai", "vllm-openai", "glm-openai"}
}

func (p *OpenAIProvider) Target(model *dto.ModelEndpoint) modelapi.ModelTarget {
	return NewModelOpenAI(model)
}

type ModelOpenAI struct {
	model      *dto.ModelEndpoint
	prometheus rpc.Prometheus
}

var (
	_ modelapi.ModelTarget = (*ModelOpenAI)(nil)
)

func NewModelOpenAI(model *dto.ModelEndpoint) *ModelOpenAI {
	return &ModelOpenAI{model: model, prometheus: impl.DefaultPrometheusImpl}
}

func (r *ModelOpenAI) GenerateImage(ctx context.Context, req *dto.GenerateImageRequest) (*dto.GenerateImageResponse, error) {
	panic("not implemented")
}

func GenerateGlmToken(ctx context.Context, apiKey string, expSeconds int64) (string, error) {
	apiKeySplit := strings.Split(apiKey, ".")

	if len(apiKeySplit) != 2 {
		return "", errors.New("invalid apikey")
	}

	id := apiKeySplit[0]
	secret := apiKeySplit[1]

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"api_key":   id,
		"exp":       (time.Now().Unix() + expSeconds) * 1000,
		"timestamp": time.Now().Unix() * 1000,
	})

	token.Header["sign_type"] = "SIGN"

	// Sign and get the complete encoded token as a string using the secret
	tokenString, err := token.SignedString([]byte(secret))
	if err != nil {
		return "", err
	}

	log.Infof(ctx, "GenerateToken tokenString: %s", tokenString)

	return tokenString, nil
}

func (r *ModelOpenAI) buildClient(ctx context.Context) (*azopenai.Client, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.buildClient",
		"self": r,
	})

	baseURL := r.model.BaseURL
	apiKey := r.model.APIKey

	if r.model.Provider == "glm-openai" {
		token, err := GenerateGlmToken(ctx, apiKey, 3600)
		if err != nil {
			logger.Errorf(ctx, "GenerateToken error. err: %+v ", err)
			return nil, err
		}

		log.Infof(ctx, "GenerateToken token: %s", token)

		apiKey = token
	}

	keyCredential := azcore.NewKeyCredential(apiKey)

	httpClient, err := http.NewClient(baseURL, nil)
	if err != nil {
		logger.Errorf(ctx, "NewClient error. err: %+v ", err)
		return nil, err
	}

	options := &azopenai.ClientOptions{
		ClientOptions: azcore.ClientOptions{
			Transport:                       httpClient,
			InsecureAllowCredentialWithHTTP: true,
		},
	}

	var client *azopenai.Client
	if r.model.Provider == "azure-openai" {
		azureClient, err := azopenai.NewClientWithKeyCredential(baseURL, keyCredential, options)
		if err != nil {
			logger.Errorf(ctx, "NewClientWithKeyCredential error. err: %+v ", err)
			return nil, err
		}
		client = azureClient
	} else {
		openaiClient, err := azopenai.NewClientForOpenAI(baseURL, keyCredential, options)
		if err != nil {
			logger.Errorf(ctx, "NewClientForOpenAI error. err: %+v ", err)
			return nil, err
		}
		client = openaiClient
	}

	return client, nil
}

func (r *ModelOpenAI) buildChatRequest(ctx context.Context, req *dto.ChatRequest) (azopenai.ChatCompletionsOptions, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.buildChatRequest",
		"self": r,
	})
	logger.Info(ctx, "req", req)

	model := r.model.Model

	messages := make([]azopenai.ChatRequestMessageClassification, 0)

	system := req.AIProfile
	if system != "" {
		messages = append(messages, &azopenai.ChatRequestSystemMessage{Content: azopenai.NewChatRequestSystemMessageContent(system)})
	}

	for _, msg := range req.Messages {
		if msg.Role == dto.ChatRequestMessageRoleSystem {
			messages = append(messages, &azopenai.ChatRequestSystemMessage{Content: azopenai.NewChatRequestSystemMessageContent(msg.Content)})
		} else if msg.Role == dto.ChatRequestMessageRoleUser {
			if msg.Images == nil {
				messages = append(messages, &azopenai.ChatRequestUserMessage{Content: azopenai.NewChatRequestUserMessageContent(msg.Content)})
			} else {
				content := make([]azopenai.ChatCompletionRequestMessageContentPartClassification, 0)
				partText := &azopenai.ChatCompletionRequestMessageContentPartText{
					Text: &msg.Content,
				}
				content = append(content, partText)

				for _, imageURL := range msg.Images {
					partImage := &azopenai.ChatCompletionRequestMessageContentPartImage{
						ImageURL: &azopenai.ChatCompletionRequestMessageContentPartImageURL{
							URL: &imageURL,
						},
					}
					content = append(content, partImage)
				}
				messages = append(messages, &azopenai.ChatRequestUserMessage{Content: azopenai.NewChatRequestUserMessageContent(content)})
			}
		} else if msg.Role == dto.ChatRequestMessageRoleAI {
			messages = append(messages, &azopenai.ChatRequestAssistantMessage{Content: azopenai.NewChatRequestAssistantMessageContent(msg.Content)})
		} else if msg.Role == dto.ChatRequestMessageRoleToolOutPut {
			messages = append(messages, &azopenai.ChatRequestToolMessage{Content: azopenai.NewChatRequestToolMessageContent(msg.Content), ToolCallID: &msg.ToolCallId})
		} else if msg.Role == dto.ChatRequestMessageRoleToolInPut {
			messages = append(messages, &azopenai.ChatRequestAssistantMessage{
				Content: azopenai.NewChatRequestAssistantMessageContent(msg.Content),
				ToolCalls: []azopenai.ChatCompletionsToolCallClassification{&azopenai.ChatCompletionsFunctionToolCall{
					ID:   to.Ptr(msg.ToolCallId),
					Type: to.Ptr("function"),
					Function: &azopenai.FunctionCall{
						Name:      to.Ptr(msg.Name),
						Arguments: to.Ptr(msg.Content),
					},
				}},
			})
		}
	}

	// 处理 Tools
	var tools []azopenai.ChatCompletionsToolDefinitionClassification
	if len(req.Tools) > 0 {
		for _, tool := range req.Tools {
			// 将 Parameters 转换为 JSON bytes
			var parametersBytes []byte
			if tool.Function.Parameters != nil {
				parametersBytes, _ = json.Marshal(tool.Function.Parameters)
			}

			azTool := &azopenai.ChatCompletionsFunctionToolDefinition{
				Type: to.Ptr("function"),
				Function: &azopenai.ChatCompletionsFunctionToolDefinitionFunction{
					Name:        to.Ptr(tool.Function.Name),
					Description: to.Ptr(tool.Function.Description),
					Parameters:  parametersBytes,
					Strict:      tool.Function.Strict,
				},
			}
			tools = append(tools, azTool)
		}
	}

	// 处理 ToolChoice
	var toolChoice *azopenai.ChatCompletionsToolChoice
	if req.ToolChoice != "" {
		switch req.ToolChoice {
		case dto.ToolChoiceOptionsNone:
			toolChoice = azopenai.ChatCompletionsToolChoiceNone
		case dto.ToolChoiceOptionsAuto:
			toolChoice = azopenai.ChatCompletionsToolChoiceAuto
		case dto.ToolChoiceOptionsRequired:
			toolChoice = azopenai.ChatCompletionsToolChoiceRequired
		}
	}
	if req.FunctionTool != "" {
		toolChoice = azopenai.NewChatCompletionsToolChoice(azopenai.ChatCompletionsToolChoiceFunction{
			Name: req.FunctionTool,
		})
	}

	options := azopenai.ChatCompletionsOptions{
		Messages:          messages,
		DeploymentName:    &model,
		MaxTokens:         req.MaxTokens,
		Stop:              req.Stop,
		Temperature:       req.Temperature,
		TopP:              req.TopP,
		GuidedChoice:      req.GuidedChoice,
		PresencePenalty:   req.PresencePenalty,
		FrequencyPenalty:  req.FrequencyPenalty,
		TopK:              req.TopK,
		RepetitionPenalty: req.RepetitionPenalty,
		Tools:             tools,
		ToolChoice:        toolChoice,
	}

	if req.ResponseFormat != nil && req.ResponseFormat.RespType != nil && *req.ResponseFormat.RespType == "json" {
		options.ResponseFormat = &azopenai.ChatCompletionsJSONResponseFormat{}
		options.GuidedJson = req.GuidedJson
	}

	if req.EnableThinking != nil {
		options.ChatTemplateKwArgs = &azopenai.ChatTemplateKwArgs{
			EnableThinking: req.EnableThinking,
		}
	}

	return options, nil
}

func (r *ModelOpenAI) buildStreamChatRequest(ctx context.Context, req *dto.ChatRequest) (azopenai.ChatCompletionsStreamOptions, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.buildStreamChatRequest",
		"self": r,
	})
	logger.Info(ctx, "req", req)

	model := r.model.Model

	messages := make([]azopenai.ChatRequestMessageClassification, 0)

	system := req.AIProfile
	if system != "" {
		messages = append(messages, &azopenai.ChatRequestSystemMessage{Content: azopenai.NewChatRequestSystemMessageContent(system)})
	}

	for _, msg := range req.Messages {
		if msg.Role == dto.ChatRequestMessageRoleSystem {
			messages = append(messages, &azopenai.ChatRequestSystemMessage{Content: azopenai.NewChatRequestSystemMessageContent(msg.Content)})
		} else if msg.Role == dto.ChatRequestMessageRoleUser {
			if msg.Images == nil {
				messages = append(messages, &azopenai.ChatRequestUserMessage{Content: azopenai.NewChatRequestUserMessageContent(msg.Content)})
			} else {
				content := make([]azopenai.ChatCompletionRequestMessageContentPartClassification, 0)
				partText := &azopenai.ChatCompletionRequestMessageContentPartText{
					Text: &msg.Content,
				}
				content = append(content, partText)

				for _, imageURL := range msg.Images {
					partImage := &azopenai.ChatCompletionRequestMessageContentPartImage{
						ImageURL: &azopenai.ChatCompletionRequestMessageContentPartImageURL{
							URL: &imageURL,
						},
					}
					content = append(content, partImage)
				}
				messages = append(messages, &azopenai.ChatRequestUserMessage{Content: azopenai.NewChatRequestUserMessageContent(content)})
			}
		} else if msg.Role == dto.ChatRequestMessageRoleAI {
			messages = append(messages, &azopenai.ChatRequestAssistantMessage{Content: azopenai.NewChatRequestAssistantMessageContent(msg.Content)})
		} else if msg.Role == dto.ChatRequestMessageRoleToolOutPut {
			messages = append(messages, &azopenai.ChatRequestToolMessage{Content: azopenai.NewChatRequestToolMessageContent(msg.Content), ToolCallID: &msg.ToolCallId})
		} else if msg.Role == dto.ChatRequestMessageRoleToolInPut {
			messages = append(messages, &azopenai.ChatRequestAssistantMessage{
				Content: azopenai.NewChatRequestAssistantMessageContent(msg.Content),
				ToolCalls: []azopenai.ChatCompletionsToolCallClassification{&azopenai.ChatCompletionsFunctionToolCall{
					ID:   to.Ptr(msg.ToolCallId),
					Type: to.Ptr("function"),
					Function: &azopenai.FunctionCall{
						Name:      to.Ptr(msg.Name),
						Arguments: to.Ptr(msg.Content),
					},
				}},
			})
		}
	}

	// 处理 Tools
	var tools []azopenai.ChatCompletionsToolDefinitionClassification
	if len(req.Tools) > 0 {
		for _, tool := range req.Tools {
			// 将 Parameters 转换为 JSON bytes
			var parametersBytes []byte
			if tool.Function.Parameters != nil {
				parametersBytes, _ = json.Marshal(tool.Function.Parameters)
			}

			azTool := &azopenai.ChatCompletionsFunctionToolDefinition{
				Type: to.Ptr("function"),
				Function: &azopenai.ChatCompletionsFunctionToolDefinitionFunction{
					Name:        to.Ptr(tool.Function.Name),
					Description: to.Ptr(tool.Function.Description),
					Parameters:  parametersBytes,
					Strict:      tool.Function.Strict,
				},
			}
			tools = append(tools, azTool)
		}
	}

	// 处理 ToolChoice
	var toolChoice *azopenai.ChatCompletionsToolChoice
	if req.ToolChoice != "" {
		switch req.ToolChoice {
		case dto.ToolChoiceOptionsNone:
			toolChoice = azopenai.ChatCompletionsToolChoiceNone
		case dto.ToolChoiceOptionsAuto:
			toolChoice = azopenai.ChatCompletionsToolChoiceAuto
		case dto.ToolChoiceOptionsRequired:
			toolChoice = azopenai.ChatCompletionsToolChoiceRequired
		}
	}
	if req.FunctionTool != "" {
		toolChoice = azopenai.NewChatCompletionsToolChoice(azopenai.ChatCompletionsToolChoiceFunction{
			Name: req.FunctionTool,
		})
	}

	options := azopenai.ChatCompletionsStreamOptions{
		Messages:          messages,
		DeploymentName:    &model,
		MaxTokens:         req.MaxTokens,
		Stop:              req.Stop,
		Temperature:       req.Temperature,
		TopP:              req.TopP,
		GuidedChoice:      req.GuidedChoice,
		PresencePenalty:   req.PresencePenalty,
		FrequencyPenalty:  req.FrequencyPenalty,
		TopK:              req.TopK,
		RepetitionPenalty: req.RepetitionPenalty,
		StreamOptions: &azopenai.ChatCompletionStreamOptions{
			IncludeUsage: lo.ToPtr(true),
		},
		Tools:      tools,
		ToolChoice: toolChoice,
	}

	if req.ResponseFormat != nil && req.ResponseFormat.RespType != nil && *req.ResponseFormat.RespType == "json" {
		options.ResponseFormat = &azopenai.ChatCompletionsJSONResponseFormat{}
		options.GuidedJson = req.GuidedJson
	}

	if req.EnableThinking != nil {
		options.ChatTemplateKwArgs = &azopenai.ChatTemplateKwArgs{
			EnableThinking: req.EnableThinking,
		}
	}

	if req.ThinkingType != "" {
		options.Thinking = &azopenai.Thinking{
			Type: lo.ToPtr(req.ThinkingType),
		}
	}

	return options, nil
}

func (r *ModelOpenAI) buildResponsesRequest(ctx context.Context, req *dto.ChatRequest) (responses.ResponseNewParams, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.buildResponsesRequest",
		"self": r,
	})
	logger.Info(ctx, "req", req)

	model := r.model.Model

	// 构建输入项列表
	inputItems := make([]responses.ResponseInputItemUnionParam, 0)

	// 添加系统提示词
	if req.AIProfile != "" && req.PreviousResponseId == "" {
		inputItems = append(inputItems, responses.ResponseInputItemParamOfMessage(
			req.AIProfile,
			responses.EasyInputMessageRoleSystem,
		))
	}

	// 添加用户消息
	for _, msg := range req.Messages {
		if msg.Role == dto.ChatRequestMessageRoleSystem {
			inputItems = append(inputItems, responses.ResponseInputItemParamOfMessage(
				msg.Content,
				responses.EasyInputMessageRoleSystem,
			))
		} else if msg.Role == dto.ChatRequestMessageRoleUser {
			inputItems = append(inputItems, responses.ResponseInputItemParamOfMessage(
				msg.Content,
				responses.EasyInputMessageRoleUser,
			))
		} else if msg.Role == dto.ChatRequestMessageRoleAI {
			inputItems = append(inputItems, responses.ResponseInputItemParamOfMessage(
				msg.Content,
				responses.EasyInputMessageRoleAssistant,
			))
		} else if msg.Role == dto.ChatRequestMessageRoleToolInPut {
			inputItems = append(inputItems, responses.ResponseInputItemParamOfFunctionCall(
				msg.Content,
				msg.ToolCallId,
				msg.Name,
			))
		} else if msg.Role == dto.ChatRequestMessageRoleToolOutPut {
			inputItems = append(inputItems, responses.ResponseInputItemParamOfFunctionCallOutput(
				msg.ToolCallId,
				msg.Content))
		}

	}

	// 构建请求参数
	requestParam := responses.ResponseNewParams{
		Model: model,
		Input: responses.ResponseNewParamsInputUnion{
			OfInputItemList: inputItems,
		},
	}

	if req.MaxTokens != nil {
		requestParam.MaxOutputTokens = param.NewOpt(int64(*req.MaxTokens))
	}
	if req.Temperature != nil {
		requestParam.Temperature = param.NewOpt(float64(*req.Temperature))
	}
	if req.TopP != nil {
		requestParam.TopP = param.NewOpt(float64(*req.TopP))
	}
	if req.PreviousResponseId != "" {
		requestParam.PreviousResponseID = param.NewOpt(req.PreviousResponseId)
	}

	if len(req.Tools) > 0 {
		toolsArray := make([]responses.ToolUnionParam, 0, len(req.Tools))
		for _, tool := range req.Tools {
			toolParam := responses.FunctionToolParam{
				Name:        tool.Function.Name,
				Description: param.NewOpt(tool.Function.Description),
				Parameters:  tool.Function.Parameters,
				Strict:      param.NewOpt(lo.FromPtr(tool.Function.Strict)),
			}
			toolsArray = append(toolsArray, responses.ToolUnionParam{
				OfFunction: &toolParam,
			})
		}
		requestParam.Tools = toolsArray
	}

	// 处理 ToolChoice
	if req.ToolChoice != "" {
		requestParam.ToolChoice = responses.ResponseNewParamsToolChoiceUnion{
			OfToolChoiceMode: param.NewOpt(responses.ToolChoiceOptions(req.ToolChoice)),
		}
	}

	// 处理 FunctionTool
	if req.FunctionTool != "" {
		requestParam.ToolChoice = responses.ResponseNewParamsToolChoiceUnion{
			OfFunctionTool: &responses.ToolChoiceFunctionParam{
				Name: req.FunctionTool,
			},
		}
	}

	return requestParam, nil
}

func chatCompletionsIntoChatResponse(ctx context.Context, resp azopenai.ChatCompletions) *dto.ChatResponse {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.chatCompletionsIntoChatResponse",
	})

	var oneChoice *azopenai.ChatChoice
	for _, choice := range resp.Choices {
		oneChoice = &choice
	}

	if oneChoice == nil || oneChoice.Message == nil || (oneChoice.Message.Content == nil && oneChoice.Message.ReasoningContent == nil) {
		logger.Errorf(ctx, "GetChatCompletions choice is empty. oneChoice: %+v ", oneChoice)
		return nil
	}

	usage := chatCompletionsUsageIntoChatResponseUsage(ctx, resp.Usage)

	content := ""
	reasoningContent := ""
	functionCallResults := make([]dto.FunctionCallResult, 0)

	if oneChoice.Message.Content != nil {
		content = *oneChoice.Message.Content
	}

	if oneChoice.Message.ReasoningContent != nil {
		reasoningContent = *oneChoice.Message.ReasoningContent
	}

	for _, toolCall := range oneChoice.Message.ToolCalls {
		// 处理不同类型的 toolCall
		switch tc := toolCall.(type) {
		case *azopenai.ChatCompletionsFunctionToolCall:
			// 处理函数调用
			if tc.Function != nil {
				var id string
				if tc.ID != nil {
					id = *tc.ID
				}
				functionCallResults = append(functionCallResults, dto.FunctionCallResult{
					Name:      *tc.Function.Name,
					Arguments: *tc.Function.Arguments,
					Type:      "function",
					ID:        id,
				})
			}
		case azopenai.ChatCompletionsToolCallClassification:
			// 处理工具调用分类
			if funcCall, ok := tc.(*azopenai.ChatCompletionsFunctionToolCall); ok && funcCall.Function != nil {
				var id string
				if funcCall.ID != nil {
					id = *funcCall.ID
				}
				functionCallResults = append(functionCallResults, dto.FunctionCallResult{
					Name:      *funcCall.Function.Name,
					Arguments: *funcCall.Function.Arguments,
					Type:      "function",
					ID:        id,
				})
			}
		}
	}

	chatResponse := &dto.ChatResponse{
		Content:             content,
		ReasoningContent:    reasoningContent,
		Usage:               usage,
		FunctionCallResults: functionCallResults,
	}

	return chatResponse
}

func chatCompletionsUsageIntoChatResponseUsage(ctx context.Context, usage *azopenai.CompletionsUsage) *dto.ChatResponseUsage {
	if usage == nil {
		return nil
	}

	inputTokenCount := int64(0)
	outputTokenCount := int64(0)

	if usage != nil {
		if usage.PromptTokens != nil {
			inputTokenCount = int64(*usage.PromptTokens)
		}

		if usage.CompletionTokens != nil {
			outputTokenCount = int64(*usage.CompletionTokens)
		}
	}

	respUsage := &dto.ChatResponseUsage{
		InputTokenCount:  inputTokenCount,
		OutputTokenCount: outputTokenCount,
	}

	return respUsage
}

func chatCompletionsStreamIntoString(ctx context.Context, chatCompletions azopenai.ChatCompletions) (string, string) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.chatCompletionsStreamIntoChatResponse",
	})

	deltaContent := ""
	deltaReasoningContent := ""

	for i, choice := range chatCompletions.Choices {
		if choice.Delta == nil || (choice.Delta.Content == nil && choice.Delta.ReasoningContent == nil) {
			logger.Infof(ctx, "GetChatCompletions choice is empty. i: %d choice: %+v ", i, choice)
			continue
		}

		if choice.Delta.Content != nil {
			deltaContent += *choice.Delta.Content
		}

		if choice.Delta.ReasoningContent != nil {
			deltaReasoningContent += *choice.Delta.ReasoningContent
		}
	}
	return deltaContent, deltaReasoningContent
}

func (r *ModelOpenAI) Chat(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error) {
	haloSpan := halo.NewHalo(ctx, "AISP_ModelOpenAI_Chat", req.ModelName)
	nowTime := time.Now()
	defer func() { haloSpan.EndWithContext(ctx, time.Since(nowTime), nil) }()

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.Chat",
	})

	client, err := r.buildClient(ctx)
	if err != nil {
		logger.Errorf(ctx, "buildClient error. req: %+v err: %+v ", req, err)
		return nil, err
	}

	options, err := r.buildChatRequest(ctx, req)
	if err != nil {
		logger.Errorf(ctx, "buildChatRequest error. req: %+v err: %+v ", req, err)
		return nil, err
	}

	// TODO: @wanghao11 接入failsafe
	startTime := time.Now()
	resp, err := client.GetChatCompletions(ctx, options, nil)
	r.statsKlaraRequest(ctx, startTime, err != nil, false)

	if err != nil {
		logger.Errorf(ctx, "GetChatCompletions error. req: %+v err: %+v ", req, err)
		return nil, err
	}

	chatResponse := chatCompletionsIntoChatResponse(ctx, resp.ChatCompletions)
	if chatResponse == nil {
		logger.Errorf(ctx, "chatCompletionsIntoChatResponse is empty. req: %+v resp.ChatCompletions: %+v ", req, resp.ChatCompletions)
		return nil, err
	}

	chatResponse.ModelName = req.ModelName

	return chatResponse, nil
}

func (r *ModelOpenAI) statsKlaraRequest(ctx context.Context, startTime time.Time, hasErr bool, isFirstToken bool) {
	isvcName, nameSpace, cluster := util.GetIsvcAndNameSpace(r.model)
	level := r.prometheus.CacheGetModelLevel(ctx, isvcName, cluster)

	status := macro.SUCCEED
	if hasErr {
		if ctx.Err() == context.Canceled {
			status = macro.CANCELED
		} else {
			status = macro.FAILED
		}
	}

	if isFirstToken {
		// 新
		util.Increment(ctx, macro.KlaraRequestCntStatsFmt, isvcName, nameSpace, status, "0")
		// 老
		statsd.Increment(fmt.Sprintf(macro.OriginKlaraRequestCntStatsFmt, isvcName, nameSpace, level, status, 0))
	}

	if !hasErr {
		if isFirstToken {
			// 新
			util.Timing(ctx, macro.KlaraRequestFirstTimeStatsFmt, time.Since(startTime), isvcName, nameSpace)
			// 老
			statsd.Timing(fmt.Sprintf(macro.OriginKlaraRequestFirstTimeStatsFmt, isvcName, nameSpace, level), time.Since(startTime))
		} else {
			// 新
			util.Timing(ctx, macro.KlaraRequestTotalTimeStatsFmt, time.Since(startTime), isvcName, nameSpace)
			// 老
			statsd.Timing(fmt.Sprintf(macro.OriginKlaraRequestTotalTimeStatsFmt, isvcName, nameSpace, level), time.Since(startTime))
		}
	}
}

func (r *ModelOpenAI) StreamChat(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse] {
	haloSpan := halo.NewHalo(ctx, "AISP_ModelOpenAI_StreamChat", req.ModelName)
	haloFTSpan := halo.NewHalo(ctx, "AISP_ModelOpenAI_StreamChat_FirstToken", req.ModelName)
	isFirstToken := true
	nowTime := time.Now()

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.StreamChat",
	})

	ret := make(chan util.Progress[*dto.ChatResponse])

	utils.SafelyGo(func() {
		defer close(ret)
		defer func() { haloSpan.EndWithContext(ctx, time.Since(nowTime), nil) }()

		defer func() {
			if err := recover(); err != nil {
				logger.WithField(ctx, "err", err).Error(ctx, "panic in StreamChat")
				ret <- util.Progress[*dto.ChatResponse]{E: fmt.Errorf("%v", err)}
			}
		}()

		client, err := r.buildClient(ctx)
		if err != nil {
			logger.Errorf(ctx, "buildClient error. req: %+v err: %+v ", req, err)
			log.StatsdError(ctx, "ModelOpenAI.StreamChat", req.ModelName, "build_client_error")
			r.statsKlaraRequest(ctx, nowTime, err != nil, false)
			ret <- util.Progress[*dto.ChatResponse]{E: err}
			return
		}

		options, err := r.buildStreamChatRequest(ctx, req)
		if err != nil {
			logger.Errorf(ctx, "buildChatRequest error. req: %+v err: %+v ", req, err)
			log.StatsdError(ctx, "ModelOpenAI.StreamChat", req.ModelName, "build_chat_request_error")
			r.statsKlaraRequest(ctx, nowTime, err != nil, false)
			ret <- util.Progress[*dto.ChatResponse]{E: err}
			return
		}

		resp, err := client.GetChatCompletionsStream(ctx, options, nil)

		if err != nil {
			logger.Errorf(ctx, "GetChatCompletions error. req: %+v err: %+v ", req, err)
			log.StatsdError(ctx, "ModelOpenAI.StreamChat", req.ModelName, "get_chat_completions_stream_error")
			r.statsKlaraRequest(ctx, nowTime, err != nil, false)
			ret <- util.Progress[*dto.ChatResponse]{E: err}
			return
		}

		defer resp.ChatCompletionsStream.Close()

		content := ""
		reasoningContent := ""
		for {
			chatCompletions, err := resp.ChatCompletionsStream.Read()

			if errors.Is(err, io.EOF) {
				log.StatsdError(ctx, "ModelOpenAI.StreamChat", req.ModelName, "EOF")

				break
			}

			if err != nil {
				if err == context.Canceled {
					tag := "unknown"
					if ctx.Err() == context.Canceled {
						tag = "client"
					}
					log.StatsdError(ctx, "ModelOpenAI.StreamChat", req.ModelName, fmt.Sprintf("%s_ctx_cancel", tag))
					logger.WithError(ctx, err).Error(ctx, fmt.Sprintf("%s context cancel in :%v", tag, time.Since(log.GetBeginTimeFromContext(ctx))))
				}

				logger.WithError(ctx, err).Error(ctx, "failed to call api")
				log.StatsdError(ctx, "ModelOpenAI.StreamChat", req.ModelName, "unknown")
				r.statsKlaraRequest(ctx, nowTime, err != nil, false)
				ret <- util.Progress[*dto.ChatResponse]{E: err}
				return
			}

			deltaContent, deltaReasoningContent := chatCompletionsStreamIntoString(ctx, chatCompletions)
			content += deltaContent
			reasoningContent += deltaReasoningContent
			usage := chatCompletionsUsageIntoChatResponseUsage(ctx, chatCompletions.Usage)

			chatResponse := &dto.ChatResponse{
				Content:          content,
				ReasoningContent: reasoningContent,
				Usage:            usage,
			}

			chatResponse.ModelName = req.ModelName

			ret <- util.Progress[*dto.ChatResponse]{V: chatResponse}

			if isFirstToken && (deltaContent != "" || deltaReasoningContent != "") {
				haloFTSpan.EndWithContext(ctx, time.Since(nowTime), nil)
				r.statsKlaraRequest(ctx, nowTime, err != nil, true)
				isFirstToken = false
			}
		}
		r.statsKlaraRequest(ctx, nowTime, err != nil, false)
		return
	}, func(_ error) {})

	return ret
}

func (r *ModelOpenAI) buildOpenAiClient(ctx context.Context) *openai.Client {
	baseURL := r.model.BaseURL
	apiKey := r.model.APIKey

	// 使用全局 HTTP 客户端，实现连接复用
	httpClient := getGlobalHTTPClient()

	// 创建 OpenAI 客户端，使用全局 HTTP 客户端
	client := openai.NewClient(
		option.WithBaseURL(baseURL),
		option.WithAPIKey(apiKey),
		option.WithHTTPClient(httpClient), // 使用全局 HTTP 客户端
		option.WithRequestTimeout(15*time.Minute),
	)

	return &client
}

func (r *ModelOpenAI) Responses(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error) {
	haloSpan := halo.NewHalo(ctx, "AISP_ModelOpenAI_Responses", req.ModelName)
	nowTime := time.Now()
	defer func() { haloSpan.EndWithContext(ctx, time.Since(nowTime), nil) }()

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.Responses",
	})

	// 构建 OpenAI 客户端
	client := r.buildOpenAiClient(ctx)
	if client == nil {
		logger.Errorf(ctx, "buildOpenAiClient error. req: %+v err: %+v ", req, "client is nil")
		return nil, fmt.Errorf("buildOpenAiClient error")
	}

	// 构建请求参数
	requestParam, err := r.buildResponsesRequest(ctx, req)
	if err != nil {
		logger.Errorf(ctx, "buildResponsesRequest error. req: %+v err: %+v ", req, err)
		return nil, err
	}

	// 添加额外的请求参数，如 extraBody
	var options []option.RequestOption
	for k, v := range req.ExtraBody {
		options = append(options, option.WithJSONSet(k, v))
	}

	var response *responses.Response

	response, err = client.Responses.New(ctx, requestParam, options...)

	if err != nil || response == nil {
		logger.Errorf(ctx, "Failed to openai Responses. err: %+v ", err)
		return nil, err
	}

	// 解析响应内容
	content := ""
	reasoningContent := ""
	functionCallResults := make([]dto.FunctionCallResult, 0)

	if len(response.Output) > 0 {
		for _, outputItem := range response.Output {
			// 根据输出项类型提取内容
			switch outputItem.Type {
			case "message":
				message := outputItem.AsMessage()
				if len(message.Content) > 0 {
					for _, contentPart := range message.Content {
						if contentPart.Type == "output_text" {
							textContent := contentPart.AsOutputText()
							content += textContent.Text
						}
					}
				}
			case "reasoning":
				reasoningItem := outputItem.AsReasoning()
				if len(reasoningItem.Content) > 0 {
					for _, contentPart := range reasoningItem.Content {
						reasoningContent += contentPart.Text
					}
				}
			case "function_call":
				functionCall := outputItem.AsFunctionCall()
				functionCallResults = append(functionCallResults, dto.FunctionCallResult{
					Name:      functionCall.Name,
					Arguments: functionCall.Arguments,
					Type:      string(functionCall.Type),
					ID:        functionCall.ID,
				})
			}
		}
	}

	// 解析 usage 信息
	var usage *dto.ChatResponseUsage
	if response.Usage.InputTokens != 0 || response.Usage.OutputTokens != 0 {
		usage = &dto.ChatResponseUsage{
			InputTokenCount:  response.Usage.InputTokens,
			OutputTokenCount: response.Usage.OutputTokens,
		}
	}

	// 构建响应
	chatResponse := &dto.ChatResponse{
		ModelName:           req.ModelName,
		Content:             content,
		ReasoningContent:    reasoningContent,
		ResponseId:          response.ID,
		Usage:               usage,
		FunctionCallResults: functionCallResults,
	}

	return chatResponse, nil
}

func (r *ModelOpenAI) StreamResponses(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse] {
	haloSpan := halo.NewHalo(ctx, "AISP_ModelOpenAI_StreamResponses", req.ModelName)
	haloFTSpan := halo.NewHalo(ctx, "AISP_ModelOpenAI_StreamResponses_FirstToken", req.ModelName)
	isFirstToken := true
	nowTime := time.Now()

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ModelOpenAI.StreamResponses",
	})

	ret := make(chan util.Progress[*dto.ChatResponse])

	utils.SafelyGo(func() {
		defer close(ret)
		defer func() { haloSpan.EndWithContext(ctx, time.Since(nowTime), nil) }()

		defer func() {
			if err := recover(); err != nil {
				logger.WithField(ctx, "err", err).Error(ctx, "panic in StreamResponses")
				ret <- util.Progress[*dto.ChatResponse]{E: fmt.Errorf("%v", err)}
			}
		}()

		// 构建 OpenAI 客户端
		client := r.buildOpenAiClient(ctx)
		if client == nil {
			logger.Errorf(ctx, "buildOpenAiClient error. req: %+v err: %+v ", req, "client is nil")
			log.StatsdError(ctx, "ModelOpenAI.StreamResponses", req.ModelName, "build_client_error")
			r.statsKlaraRequest(ctx, nowTime, true, false)
			ret <- util.Progress[*dto.ChatResponse]{E: fmt.Errorf("buildOpenAiClient error")}
			return
		}

		// 构建请求参数
		requestParam, err := r.buildResponsesRequest(ctx, req)

		if err != nil {
			logger.Errorf(ctx, "buildResponsesRequest error. req: %+v err: %+v ", req, err)
			log.StatsdError(ctx, "ModelOpenAI.StreamResponses", req.ModelName, "build_responses_request_error")
			r.statsKlaraRequest(ctx, nowTime, true, false)
			ret <- util.Progress[*dto.ChatResponse]{E: err}
			return
		}

		// 添加额外的请求参数，如 extraBody
		var options []option.RequestOption
		for k, v := range req.ExtraBody {
			options = append(options, option.WithJSONSet(k, v))
		}

		// 使用流式 API，返回的是 ResponseStreamEventUnion 流
		stream := client.Responses.NewStreaming(ctx, requestParam, options...)

		if stream.Err() != nil {
			logger.Errorf(ctx, "NewStreaming error. req: %+v err: %+v ", req, stream.Err())
			log.StatsdError(ctx, "ModelOpenAI.StreamResponses", req.ModelName, "new_streaming_error")
			r.statsKlaraRequest(ctx, nowTime, true, false)
			ret <- util.Progress[*dto.ChatResponse]{E: stream.Err()}
			return
		}

		// 累积的内容
		content := ""
		reasoningContent := ""
		functionCallResults := make([]dto.FunctionCallResult, 0)
		var responseId string
		var usage *dto.ChatResponseUsage
		// 用于累积函数调用参数
		currentFunctionCallArgs := make(map[string]string) // itemID -> arguments

		// 遍历流式事件
		for stream.Next() {
			event := stream.Current()

			// 根据事件类型处理
			switch event.Type {
			case string(constant.ValueOf[constant.ResponseCreated]()):
				// 响应创建，提取 ResponseId
				if event.Response.ID != "" {
					responseId = event.Response.ID
				}

			case string(constant.ValueOf[constant.ResponseOutputTextDelta]()):
				// 输出文本增量
				deltaText := ""
				if event.Delta != "" {
					deltaText = event.Delta
				} else if event.Text != "" {
					deltaText = event.Text
				}
				if deltaText != "" {
					content += deltaText

					chatResponse := &dto.ChatResponse{
						ModelName:           req.ModelName,
						Content:             content,
						ReasoningContent:    reasoningContent,
						ResponseId:          responseId,
						Usage:               usage,
						FunctionCallResults: functionCallResults,
					}

					ret <- util.Progress[*dto.ChatResponse]{V: chatResponse}

					// 检查是否是第一个 token
					if isFirstToken {
						haloFTSpan.EndWithContext(ctx, time.Since(nowTime), nil)
						r.statsKlaraRequest(ctx, nowTime, false, true)
						isFirstToken = false
					}
				}

			case string(constant.ValueOf[constant.ResponseReasoningSummaryTextDelta]()):
				// 推理摘要文本增量（思考过程）
				deltaText := ""
				if event.Delta != "" {
					deltaText = event.Delta
				} else if event.Text != "" {
					deltaText = event.Text
				}
				if deltaText != "" {
					reasoningContent += deltaText

					chatResponse := &dto.ChatResponse{
						ModelName:           req.ModelName,
						Content:             content,
						ReasoningContent:    reasoningContent,
						ResponseId:          responseId,
						Usage:               usage,
						FunctionCallResults: functionCallResults,
					}

					ret <- util.Progress[*dto.ChatResponse]{V: chatResponse}

					// 检查是否是第一个 token
					if isFirstToken {
						haloFTSpan.EndWithContext(ctx, time.Since(nowTime), nil)
						r.statsKlaraRequest(ctx, nowTime, false, true)
						isFirstToken = false
					}
				}

			case string(constant.ValueOf[constant.ResponseOutputItemAdded]()):
				// 输出项添加（如 function_call）
				if event.Item.Type == "function_call" {
					functionCall := event.Item.AsFunctionCall()
					itemID := event.ItemID
					if itemID != "" {
						// 初始化函数调用参数累积
						currentFunctionCallArgs[itemID] = ""
						functionCallResults = append(functionCallResults, dto.FunctionCallResult{
							Name:      functionCall.Name,
							Arguments: "", // 参数会通过 delta 事件累积
							Type:      string(functionCall.Type),
							ID:        itemID,
						})
					}
				}

			case string(constant.ValueOf[constant.ResponseFunctionCallArgumentsDelta]()):
				// 函数调用参数增量
				if event.Arguments != "" {
					itemID := event.ItemID
					if itemID != "" {
						// 累积函数调用参数
						currentFunctionCallArgs[itemID] += event.Arguments
						// 更新对应的 functionCallResult
						for i := range functionCallResults {
							if functionCallResults[i].ID == itemID {
								functionCallResults[i].Arguments = currentFunctionCallArgs[itemID]
								break
							}
						}

						// 发送更新后的响应
						chatResponse := &dto.ChatResponse{
							ModelName:           req.ModelName,
							Content:             content,
							ReasoningContent:    reasoningContent,
							ResponseId:          responseId,
							Usage:               usage,
							FunctionCallResults: functionCallResults,
						}

						ret <- util.Progress[*dto.ChatResponse]{V: chatResponse}
					}
				}

			case string(constant.ValueOf[constant.ResponseCompleted]()):
				// 响应完成，提取完整的 usage 信息
				if event.Response.Usage.InputTokens != 0 || event.Response.Usage.OutputTokens != 0 {
					usage = &dto.ChatResponseUsage{
						InputTokenCount:  event.Response.Usage.InputTokens,
						OutputTokenCount: event.Response.Usage.OutputTokens,
					}
				}

				// 发送最终响应
				chatResponse := &dto.ChatResponse{
					ModelName:           req.ModelName,
					Content:             content,
					ReasoningContent:    reasoningContent,
					ResponseId:          responseId,
					Usage:               usage,
					FunctionCallResults: functionCallResults,
				}

				ret <- util.Progress[*dto.ChatResponse]{V: chatResponse}

			case string(constant.ValueOf[constant.Error]()):
				// 错误事件
				logger.Errorf(ctx, "Stream error event. message: %s param: %s", event.Message, event.Param)
				log.StatsdError(ctx, "ModelOpenAI.StreamResponses", req.ModelName, "stream_error_event")
				r.statsKlaraRequest(ctx, nowTime, true, false)
				ret <- util.Progress[*dto.ChatResponse]{E: fmt.Errorf("stream error: %s (param: %s)", event.Message, event.Param)}
				return
			}
		}

		// 检查流式读取的错误
		if stream.Err() != nil {
			err := stream.Err()
			if err == context.Canceled || errors.Is(err, context.Canceled) {
				tag := "unknown"
				if ctx.Err() == context.Canceled {
					tag = "client"
				}
				log.StatsdError(ctx, "ModelOpenAI.StreamResponses", req.ModelName, fmt.Sprintf("%s_ctx_cancel", tag))
				logger.WithError(ctx, err).Error(ctx, fmt.Sprintf("%s context cancel in :%v", tag, time.Since(log.GetBeginTimeFromContext(ctx))))
			} else {
				logger.WithError(ctx, err).Error(ctx, "failed to read stream")
				log.StatsdError(ctx, "ModelOpenAI.StreamResponses", req.ModelName, "stream_read_error")
			}
			r.statsKlaraRequest(ctx, nowTime, true, false)
			ret <- util.Progress[*dto.ChatResponse]{E: err}
			return
		}

		// 流式读取完成
		r.statsKlaraRequest(ctx, nowTime, false, false)
		return
	}, func(_ error) {})

	return ret
}
