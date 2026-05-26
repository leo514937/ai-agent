package rpc

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	mapset "github.com/deckarep/golang-set"
	"github.com/sashabaranov/go-openai"
)

type KlaraHttp interface {
	// InvokeVLLM 调用 VLLM 模型接口
	InvokeVLLM(ctx context.Context, url KlaraLLMUrl, request CompletionRequest) (*openai.CompletionResponse, error)
	// InvokePost 调用 Klara 非框架接口
	InvokePost(ctx context.Context, url KlaraServiceUrl, requestJson []byte, result any)
	// BatchInferPairwiseScoreBySize 批量计算 pairwise score
	BatchInferPairwiseScoreBySize(ctx context.Context, url KlaraServiceUrl, request KlaraRerankRequest, batchSize int) []float32
	// ConcurrentInferEmbedding 并发计算 embedding
	ConcurrentInferEmbedding(ctx context.Context, url KlaraServiceUrl, inputTexts []string, modelName string) [][]float32
}

// KlaraServiceUrl 服务类型
type KlaraServiceUrl string

const (
	// KlaraServiceUrlQueryIntention 意图识别
	KlaraServiceUrlQueryIntention KlaraServiceUrl = "http://intention-recognition.jeeves-agi.klara.pek02.rack.zhihu.com:8080/api/v2/infer"
	// KlaraServiceUrlInterestWord 兴趣词
	KlaraServiceUrlInterestWord KlaraServiceUrl = "http://feed-keywords-expand.jeeves-agi.klara.pek02.rack.zhihu.com:8080/api/v2/infer"
	// KlaraServiceUrlImageFace 图片是否包含人脸
	KlaraServiceUrlImageFace KlaraServiceUrl = "http://image-face-analysis.jeeves-agi.klara.pek02.rack.zhihu.com:8080/api/infer"
	// KlaraServiceUrlBgeRerank BGE rerank
	KlaraServiceUrlBgeRerank    KlaraServiceUrl = "http://bge-reranker-v2-m3.jeeves-agi.klara.pek02.rack.zhihu.com:8080/rerank"
	KlaraServiceUrlZhiRerankMix KlaraServiceUrl = "http://zhi-reraner-mix-sjhl.jeeves-agi.klara-sjhl-isolated-1.pek02.rack.zhihu.com:8080/rerank"

	// KlaraServiceUrlZhiEmb zhi-embedding
	KlaraServiceUrlZhiEmb KlaraServiceUrl = macro.ModelProxyUrl + "/embeddings"
)

var OpenAiServiceUrlList = mapset.NewSet(
	KlaraServiceUrlZhiEmb,
)

// KlaraLLMUrl LLM
type KlaraLLMUrl string

const (
	// KlaraLLMQueryMerge QueryMerge
	KlaraLLMQueryMerge KlaraLLMUrl = "http://query-merge-v2.jeeves-agi.klara.pek02.rack.zhihu.com:8080/v1"
	// KlaraServiceUrlTask 任务判别
	KlaraServiceUrlTask KlaraLLMUrl = "http://multi-chat-task-info.jeeves-agi.klara.pek02.rack.zhihu.com:8080/v1"
	// KlaraMultiChatSummary 多轮对话生成summary
	KlaraMultiChatSummary KlaraLLMUrl = "http://multi-chat-summary.jeeves-agi.klara.pek02.rack.zhihu.com:8080/v1"
)

// KlaraInferType 推理类型
type KlaraInferType string

const (
	KlaraInferTypeNormal      KlaraInferType = "normal"
	KlaraInferTypeGreedyMatch KlaraInferType = "greedy_match"
	KlaraInferTypeLogProb     KlaraInferType = "log_prob"
	KlaraInferTypeRandGen     KlaraInferType = "rand_gen"
	KlaraInferTypeLoss        KlaraInferType = "loss"
)

type KlaraModelName string

const KlaraModelNameZhiEmbedding KlaraModelName = "zhi-embedding-prompt-zhida"

type KlaraRequestBody struct {
	Params    KlaraRequestParams      `json:"params"`    // 参数
	Instances []KlaraRequestInstances `json:"instances"` // instances
}
type KlaraRequestParams struct {
	Token       string         `json:"token"`      // 凭证
	MaxLength   int64          `json:"max_length"` // 最大长度
	BeamSize    int64          `json:"beam_size"`  // 模型
	Escape      bool           `json:"escape"`
	Temperature float64        `json:"temperature"` // 温度参数，调节多样性
	InferType   KlaraInferType `json:"infer_type"`  // Klara推理类型
	TopP        float64        `json:"top_p"`
	TopK        int64          `json:"top_k"`
}
type KlaraRequestInstances struct {
	// Input 格式 Context: Format后的(prompt,question)
	Input string `json:"input"` // 输入
	// Options 默认 {}
	Options string `json:"options"` // 其他参数
	// Ans 默认 ""
	Ans string `json:"<ans>"` //
}

type KlaraResponse struct {
	ErrorCode    int64                     `json:"error_code"`    // 异常编码
	ErrorMsg     string                    `json:"error_msg"`     // 异常信息
	Model        string                    `json:"model"`         // 模型
	ModelVersion string                    `json:"model_version"` // 模型版本
	CostMs       int64                     `json:"cost_ms"`       // 总耗时
	Data         []KlaraResponseResultData `json:"data"`          // 数据
}

type KlaraResponseResultData struct {
	Result      KlaraResponseResult `json:"result"`       // 异常编码
	TimeElapsed float64             `json:"time_elapsed"` // 单个实例耗时
}

type KlaraResponseResult struct {
	Document string `json:"document"`
	Ans      string `json:"<ans>"`
}

// https://huggingface.github.io/text-embeddings-inference/
type KlaraRerankRequest struct {
	Query               string   `json:"query"`
	Texts               []string `json:"texts"`
	RawScores           bool     `json:"raw_scores,omitempty"`
	ReturnText          bool     `json:"return_text,omitempty"`
	Truncate            bool     `json:"truncate,omitempty"`
	TruncationDirection string   `json:"truncation_direction,omitempty"`
}

type KlaraRerankRespItem struct {
	Index int     `json:"index"`
	Score float32 `json:"score"`
	Text  string  `json:"text,omitempty"`
}

// https://infinity.modal.michaelfeil.eu/docs#/
type KlaraEmbeddingRequest struct {
	Input string `json:"input"`
	Model string `json:"model"`
}

type KlaraEmbeddingResp struct {
	Data   []*KlaraEmbeddingRespItem `json:"data"`
	Model  string                    `json:"model"`
	Object string                    `json:"object"`
	Usage  *KlaraEmbeddingUsage      `json:"usage"`
}

type KlaraEmbeddingRespItem struct {
	Object    string    `json:"object"`
	Embedding []float32 `json:"embedding"`
	Index     int       `json:"index"`
}

type KlaraEmbeddingUsage struct {
	CompletionTokens int `json:"completion_tokens"`
	PromptTokens     int `json:"prompt_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

// =============================================================

// LLMTemplateType LLM 模板类型
type LLMTemplateType string

// 定义枚举常量
const (
	TemplateTypeChatML          LLMTemplateType = "chatml"
	TemplateTypeBaiChuan        LLMTemplateType = "baichuan"
	TemplateTypeBaiChuan2       LLMTemplateType = "baichuan2"
	TemplateTypeChatGLM2        LLMTemplateType = "chatglm2"
	TemplateTypeZephyr          LLMTemplateType = "zephyr"
	TemplateTypeOpenBuddyLlama  LLMTemplateType = "openbuddy-llama"
	TemplateTypeDefaultTemplate LLMTemplateType = "default"
)

// CompletionRequest represents a request structure for completion API.
type CompletionRequest struct {
	Model            string
	PromptContent    string
	Suffix           string
	MaxTokens        int
	Temperature      float32
	TopP             float32
	N                int
	Stream           bool
	LogProbs         int
	Echo             bool
	Stop             []string
	PresencePenalty  float32
	FrequencyPenalty float32
	BestOf           int
	// LogitBias is must be a token id string (specified by their token ID in the tokenizer), not a word string.
	// incorrect: `"logit_bias":{"You": 6}`, correct: `"logit_bias":{"1639": 6}`
	// refs: https://platform.openai.com/docs/api-reference/completions/create#completions/create-logit_bias
	LogitBias      map[string]int
	User           string
	TemplateType   LLMTemplateType
	SystemTemplate string
}
