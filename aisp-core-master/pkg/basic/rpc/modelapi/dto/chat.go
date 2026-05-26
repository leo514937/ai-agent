package dto

import (
	"encoding/json"
	"fmt"
	"reflect"
	"regexp"
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-model_gateway/model_gateway"
)

// ... existing code ...

// Tool 结构体定义
type Tool struct {
	Type     string       `json:"type"`
	Function ToolFunction `json:"function"`
}

type ToolFunction struct {
	Name        string                 `json:"name"`
	Description string                 `json:"description"`
	Parameters  map[string]interface{} `json:"parameters"`
	Strict      *bool                  `json:"strict"`
}

// ToolChoice 工具选择结构体
type ToolChoice struct {
	Type     string              `json:"type,omitempty"`
	Function *ToolChoiceFunction `json:"function,omitempty"`
}

// ToolChoiceFunction 工具选择函数结构体
type ToolChoiceFunction struct {
	Name string `json:"name"`
}

// AllowedTools 允许的工具结构体
type AllowedTools struct {
	Tools []string `json:"tools"`
}

type ChatRequest struct {
	ModelName      string                `json:"modelName"`
	Messages       []*ChatRequestMessage `json:"messages"`
	AIProfile      string                `json:"aiProfile"`
	MaxTokens      *int32
	Stop           []string
	Temperature    *float32
	TopP           *float32
	ResponseFormat *ChatCompletionsResponseFormat
	// extra
	GuidedJson         map[string]interface{}
	GuidedChoice       []string
	PresencePenalty    *float32
	FrequencyPenalty   *float32
	TopK               *int32
	RepetitionPenalty  *float32
	EnableThinking     *bool
	ThinkingType       string
	PreviousResponseId string
	ExtraBody          map[string]interface{}
	// 新增字段
	Tools        []Tool            `json:"tools,omitempty"`
	ToolChoice   ToolChoiceOptions `json:"tool_choice,omitempty"`
	FunctionTool string            `json:"function_tool,omitempty"`
}

const (
	ToolChoiceOptionsNone     ToolChoiceOptions = "none"
	ToolChoiceOptionsAuto     ToolChoiceOptions = "auto"
	ToolChoiceOptionsRequired ToolChoiceOptions = "required"
)

type ToolChoiceOptions string

type ChatCompletionsResponseFormat struct {
	RespType *string
}

type ChatRequestMessage struct {
	Images     []string               `json:"images"`
	Content    string                 `json:"content"`
	Role       ChatRequestMessageRole `json:"role"`
	ToolCallId string                 `json:"tool_call_id,omitempty"`
	Name       string                 `json:"name,omitempty"`
}

type ChatRequestMessageRole string

const (
	ChatRequestMessageRoleUser       ChatRequestMessageRole = "USER"
	ChatRequestMessageRoleAI         ChatRequestMessageRole = "AI"
	ChatRequestMessageRoleSystem     ChatRequestMessageRole = "SYSTEM"
	ChatRequestMessageRoleToolInPut  ChatRequestMessageRole = "TOOL_INPUT" // 工具调用指令，response接口用，如果是ChatCompletions接口，role选AI
	ChatRequestMessageRoleToolOutPut ChatRequestMessageRole = "TOOL"       // 工具调用结果
)

func (role ChatRequestMessageRole) ToProto() proto.ChatParam_Role {
	switch role {
	case ChatRequestMessageRoleUser:
		return proto.ChatParam_ROLE_USER
	case ChatRequestMessageRoleAI:
		return proto.ChatParam_ROLE_ASSISTANT
	case ChatRequestMessageRoleSystem:
		return proto.ChatParam_ROLE_SYSTEM
	case ChatRequestMessageRoleToolInPut:
		return proto.ChatParam_ROLE_ASSISTANT
	case ChatRequestMessageRoleToolOutPut:
		return proto.ChatParam_ROLE_FUNCTION
	default:
		panic(fmt.Sprintf("unknown role: %s", role))
	}
}

type ChatResponse struct {
	ModelName           string               `json:"model_name"`
	Content             string               `json:"content,omitempty"`
	ReasoningContent    string               `json:"reasoning_content,omitempty"`
	Usage               *ChatResponseUsage   `json:"usage"`
	ResponseId          string               `json:"response_id"`
	FunctionCallResults []FunctionCallResult `json:"function_call_results,omitempty"`
}

type FunctionCallResult struct {
	Arguments string `json:"arguments,required"`
	Name      string `json:"name,required"`
	Type      string `json:"type,required"`
	ID        string `json:"id"`
}

func (r *ChatResponse) IsEmpty(isUseThink bool) bool {
	if isUseThink {
		return r.Content == "" && r.ReasoningContent == ""
	}

	return r.Content == ""
}

var re1 = regexp.MustCompile(`<zhithink>`)
var re2 = regexp.MustCompile(`</zhithink>`)

func (r *ChatResponse) GetContent(isUseThink bool) string {
	content := ""
	rContent := r.Content

	if isUseThink && r.ReasoningContent != "" {
		reasoningContent := r.ReasoningContent
		// 分别替换<zhithink>和</zhithink>
		reasoningContent = re1.ReplaceAllString(reasoningContent, "&lt;zhithink&gt;")
		reasoningContent = re2.ReplaceAllString(reasoningContent, "&lt;/zhithink&gt;")
		// 数据清洗，去除首尾空格和换行。如果思维链为空，接口会返回 \n\n，需按无 think 处理
		reasoningContent = strings.TrimSpace(reasoningContent)
		if len(reasoningContent) > 0 {
			content = "<zhithink>\n" + reasoningContent

			if rContent != "" {
				content += "\n</zhithink>\n\n"
			}
		}
	}

	if isUseThink {
		rContent = re1.ReplaceAllString(rContent, "&lt;zhithink&gt;")
		rContent = re2.ReplaceAllString(rContent, "&lt;/zhithink&gt;")
	}

	content += rContent

	return content
}

// 校验 response functionCall 结果的合法性
func (r *ChatResponse) IsValidFunctionCallResponse(targetStruct interface{}) bool {
	if r == nil || len(r.FunctionCallResults) == 0 || r.FunctionCallResults[0].Arguments == "" {
		return false
	}

	// 验证反序列化的参数是否完整 - 检查是否包含所有必需字段
	var rawResponse map[string]interface{}
	if err := json.Unmarshal([]byte(r.FunctionCallResults[0].Arguments), &rawResponse); err != nil {
		return false
	}

	// 使用反射获取目标结构体的 JSON 标签
	structType := reflect.TypeOf(targetStruct)
	// 如果传入的是指针，获取指向的类型
	if structType.Kind() == reflect.Ptr {
		structType = structType.Elem()
	}

	for i := 0; i < structType.NumField(); i++ {
		field := structType.Field(i)
		jsonTag := field.Tag.Get("json")
		if jsonTag == "" || jsonTag == "-" {
			continue
		}

		// 解析 JSON 标签，获取字段名和选项
		jsonParts := strings.Split(jsonTag, ",")
		fieldName := jsonParts[0]

		// 跳过 omitempty 标签的字段，因为这些字段在 JSON 中可能不存在
		hasOmitEmpty := false
		for _, part := range jsonParts[1:] {
			if strings.TrimSpace(part) == "omitempty" {
				hasOmitEmpty = true
				break
			}
		}

		if hasOmitEmpty {
			continue
		}

		// 检查字段是否存在
		if _, exists := rawResponse[fieldName]; !exists {
			return false
		}
	}

	return true
}

type ChatResponseUsage struct {
	InputTokenCount  int64 `json:"input_token_count"`
	OutputTokenCount int64 `json:"output_token_count"`
}

type GenerateImageRequest struct {
	ModelName   string                   `json:"modelName"`
	Prompt      string                   `json:"prompt"`
	Images      []string                 `json:"images"`
	Hyperparams GenerateImageHyperparams `json:"hyperparams"`
}

type GenerateImageHyperparams struct {
	Size  string                 `json:"size"`
	Count int64                  `json:"count"`
	Extra map[string]interface{} `json:"extra"`
}

type GenerateImageResponse struct {
	Images []string `json:"images"`
}

func ChatContentInfoToProto(text string, images []string) []*proto.ChatParam_ChatContentInfo {

	var chatImageInfos []*proto.ChatParam_ChatContentInfo
	chatImageInfos = append(chatImageInfos, &proto.ChatParam_ChatContentInfo{
		Type: proto.ChatParam_TEXT_TYPE,
		Text: text,
	})
	if len(images) == 0 {
		return chatImageInfos
	}
	for _, imagUrl := range images {
		chatImageInfos = append(chatImageInfos, &proto.ChatParam_ChatContentInfo{
			Type: proto.ChatParam_IMAGE_URL_TYPE,
			ImageUrl: &proto.ChatParam_ImageUrl{
				Url: imagUrl,
			},
		})
	}
	return chatImageInfos
}
