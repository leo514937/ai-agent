package main

import (
	"context"
	"flag"
	"strconv"
	"time"

	"github.com/openai/openai-go/v2"
	"github.com/openai/openai-go/v2/option"
	"github.com/openai/openai-go/v2/packages/param"
	"github.com/openai/openai-go/v2/responses"
)

var baseURL = "https://model.in.zhihu.com/v1"
var apiKey = "你的 apiKey，替换到这里"
var model = "deepseek-r1-0528-baidubce" // 模型替换在这里

var client = openai.NewClient(
	option.WithBaseURL(baseURL),
	option.WithAPIKey(apiKey),
	option.WithRequestTimeout(20*time.Minute),
)

func main() {
	ctx := context.Background()
	ossUrl := flag.String("query", "hello", "你的输入query")
	isStream := flag.Bool("isStream", false, "是否流式")
	flag.Parse()

	if *isStream {
		chatCompletionsWithOpenaiSdkStream(ctx, *ossUrl)
	} else {
		chatCompletionsWithOpenaiSdk(ctx, *ossUrl)
	}
	flag.Parse()
}

func chatCompletionsWithOpenaiSdk(ctx context.Context, query string) {
	messages := make([]openai.ChatCompletionMessageParamUnion, 0)
	messages = append(messages, openai.UserMessage(query))

	completion, err := client.Chat.Completions.New(ctx,
		openai.ChatCompletionNewParams{
			Messages:    messages,
			Model:       model,
			MaxTokens:   param.NewOpt[int64](100),
			Temperature: param.NewOpt[float64](0.7),
		},
	)
	if err != nil {
		panic(err)
	}
	answer := completion.Choices[0].Message.Content

	reasoning := ""
	if completion.Choices[0].Message.JSON.ExtraFields != nil {
		if reasoningField, exists := completion.Choices[0].Message.JSON.ExtraFields["reasoning_content"]; exists {
			reasoning = reasoningField.Raw()
		}
	}

	println("========>最终思考:", reasoning)
	println("========>最终回答:", answer)
}

func chatCompletionsWithOpenaiSdkStream(ctx context.Context, query string) {
	messages := make([]openai.ChatCompletionMessageParamUnion, 0)
	messages = append(messages, openai.UserMessage(query))

	stream := client.Chat.Completions.NewStreaming(ctx,
		openai.ChatCompletionNewParams{
			Messages:    messages,
			Model:       model,
			MaxTokens:   param.NewOpt[int64](100),
			Temperature: param.NewOpt[float64](0.7),
		},
	)

	if stream.Err() != nil {
		panic(stream.Err())
	}
	answer := ""
	reasoning := ""
	for stream.Next() {
		completion := stream.Current()
		if len(completion.Choices) == 0 {
			continue
		}
		delta := completion.Choices[0].Delta
		if delta.Content != "" {
			chunkContent := delta.Content
			println("流式回答内容:", chunkContent)
			answer += chunkContent
		}
		if delta.JSON.ExtraFields != nil && delta.JSON.ExtraFields["reasoning_content"].Raw() != "" {
			chunkReasoning := delta.JSON.ExtraFields["reasoning_content"].Raw()
			if len(chunkReasoning) > 2 && chunkReasoning[0] == '"' && chunkReasoning[len(chunkReasoning)-1] == '"' {
				// 使用 strconv.Unquote 来正确处理转义字符
				if unquoted, err := strconv.Unquote(chunkReasoning); err == nil {
					chunkReasoning = unquoted
				}
			}
			println("流式思考过程:", chunkReasoning)
			reasoning += chunkReasoning
		}
	}
	if stream.Err() != nil {
		panic(stream.Err())
	}

	println("========>最终思考:", reasoning)
	println("========>最终回答:", answer)
}

// 【特殊场景】知乎内部工具使用，例如 oncall 助手，需要传递知识库进行问答的情况。
func chatCompletionsInternal(ctx context.Context, query string) {
	messages := make([]openai.ChatCompletionMessageParamUnion, 0)
	messages = append(messages, openai.UserMessage(query))

	completion, err := client.Chat.Completions.New(ctx,
		openai.ChatCompletionNewParams{
			Messages: messages,
			Model:    model,
		},
		option.WithJSONSet("personal_knowledge_base", []map[string]interface{}{
			{
				"knowledge_base_type": "PKB_INTERNAL",
				"knowledge_base_id":   123456789,
			},
		}),
		option.WithJSONSet("with_cards_in_content", true),
	)
	if err != nil {
		panic(err)
	}
	answer := completion.Choices[0].Message.Content

	println("========>最终回答:", answer)
}

// responses api
func chatResponseSetPrefixCache(ctx context.Context, query string) string {
	inputItems := []responses.ResponseInputItemUnionParam{
		responses.ResponseInputItemParamOfMessage(
			query,
			responses.EasyInputMessageRoleSystem,
		),
	}
	response, err := client.Responses.New(ctx,
		responses.ResponseNewParams{
			Model: model,
			Input: responses.ResponseNewParamsInputUnion{
				OfInputItemList: inputItems, // 使用带角色的输入列表
			},
		},
		option.WithJSONSet("caching", map[string]interface{}{
			"type": "enabled",
		}),
		option.WithJSONSet("thinking", map[string]interface{}{
			"type": "disabled",
		}),
	)
	if err != nil || response == nil {
		panic(err)
	}

	println("========>Responses接口: 设置缓存前缀，ID:", response.ID)

	return response.ID
}

func chatResponseUsePrefixCache(ctx context.Context, query string, previousResponseID string) {
	inputItems := []responses.ResponseInputItemUnionParam{
		responses.ResponseInputItemParamOfMessage(
			query,
			responses.EasyInputMessageRoleUser,
		),
	}

	response, err := client.Responses.New(ctx,
		responses.ResponseNewParams{
			Model: model,
			Input: responses.ResponseNewParamsInputUnion{
				OfInputItemList: inputItems, // 使用带角色的输入列表
			},
			PreviousResponseID: param.NewOpt(previousResponseID),
		},
		option.WithJSONSet("thinking", map[string]interface{}{
			"type": "disabled",
		}),
	)
	if err != nil {
		panic(err)
	}

	// 获取响应内容 - Response 结构体使用 Output 字段而不是 Choices
	if len(response.Output) == 0 {
		println("========>Responses接口: 没有输出内容")
		return
	}

	// 获取第一个输出项的内容
	outputItem := response.Output[0]

	// 根据输出项类型获取内容
	var answer string
	var reasoning string

	// 检查输出项类型并提取内容
	if outputItem.Type == "message" {
		// 如果是消息类型，使用 AsMessage() 方法获取具体类型
		message := outputItem.AsMessage()
		if len(message.Content) > 0 {
			for _, content := range message.Content {
				// 检查内容类型，使用 AsOutputText() 方法获取文本内容
				if content.Type == "output_text" {
					textContent := content.AsOutputText()
					answer += textContent.Text
				}
			}
		}
	} else if outputItem.Type == "reasoning" {
		// 如果是推理类型，使用 AsReasoning() 方法获取具体类型
		reasoningItem := outputItem.AsReasoning()
		if len(reasoningItem.Content) > 0 {
			for _, content := range reasoningItem.Content {
				reasoning += content.Text
			}
		}
	}

	println("========>Responses接口最终思考:", reasoning)
	println("========>Responses接口最终回答:", answer)
}
