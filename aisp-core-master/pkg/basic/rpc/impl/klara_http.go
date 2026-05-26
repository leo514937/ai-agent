package impl

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"sync"
	"text/template"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/klara_meta/impl"
	rpc2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/klara_meta/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/pkg/errors"
	"github.com/samber/lo"
	"github.com/sashabaranov/go-openai"
)

var (
	_ rpc.KlaraHttp = (*KlaraHttpImpl)(nil)
)

var llmClientMap = sync.Map{}

type KlaraHttpImpl struct {
	httpClient     *http.Client
	fastHttpClient *http.Client
	prometheus     rpc2.Prometheus
}

func NewKlaraHttpImpl(timeout time.Duration) *KlaraHttpImpl {
	return &KlaraHttpImpl{
		httpClient: &http.Client{Timeout: timeout},
		prometheus: impl.DefaultPrometheusImpl,
	}
}

func (r *KlaraHttpImpl) InvokeVLLM(
	ctx context.Context, url rpc.KlaraLLMUrl, request rpc.CompletionRequest) (*openai.CompletionResponse, error) {
	logger := log.WithField(ctx, "InvokeVLLM", request)

	clientObj, _ := llmClientMap.LoadOrStore(url, openai.NewClientWithConfig(openai.ClientConfig{
		HTTPClient: r.httpClient,
		BaseURL:    string(url),
	}))

	llmClient, converted := clientObj.(*openai.Client)
	if !converted {
		err := errors.Errorf("llm client create error (type conversion) ")
		logger.Error(ctx, err)
		return nil, err
	}

	// 根据 TemplateType 格式化 prompt
	prompt, err := r.formatPrompt(request.TemplateType, request.SystemTemplate, request.PromptContent)
	if err != nil {
		logger.Error(ctx, err)
		return nil, err
	}
	// 转换 Request
	req := openai.CompletionRequest{
		Prompt:           prompt,
		Model:            request.Model,
		Suffix:           request.Suffix,
		MaxTokens:        request.MaxTokens,
		Temperature:      request.Temperature,
		TopP:             request.TopP,
		N:                request.N,
		Stop:             request.Stop,
		Stream:           request.Stream,
		LogProbs:         request.LogProbs,
		Echo:             request.Echo,
		PresencePenalty:  request.PresencePenalty,
		FrequencyPenalty: request.FrequencyPenalty,
		BestOf:           request.BestOf,
		LogitBias:        request.LogitBias,
		User:             request.User,
	}

	var response openai.CompletionResponse
	runFunc := func(ctx context.Context) error {
		startTime := time.Now()
		responseTmp, respErr := llmClient.CreateCompletion(ctx, req)
		r.statsKlaraRequest(ctx, startTime, respErr != nil, 0, string(url))
		if respErr != nil {
			logger.Errorf(ctx, "InvokeVLLM Error => %v", respErr)
			return respErr
		}
		response = responseTmp
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return &response, nil
}

func (r *KlaraHttpImpl) InvokePost(ctx context.Context, url rpc.KlaraServiceUrl, requestJson []byte, result any) {
	logger := log.WithField(ctx, "InvokePost", string(requestJson))

	runFunc := func(ctx context.Context) error {
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, string(url), bytes.NewBuffer(requestJson))
		if err != nil {
			return err
		}

		req.Header.Add("Content-Type", "application/json; charset=UTF-8")
		req.Header.Add("Accept", "application/json")

		// 针对 openAI 协议，增加 Authorization
		if rpc.OpenAiServiceUrlList.Contains(url) {
			req.Header.Set("Authorization", "Bearer "+macro.ModelProxyAPIKey)
		}

		startTime := time.Now()
		resp, err := r.httpClient.Do(req)
		r.statsKlaraRequest(ctx, startTime, err != nil || resp == nil || resp.StatusCode != http.StatusOK, 0, string(url))
		if err != nil {
			return err
		}
		defer func() {
			bodyCloseErr := resp.Body.Close()
			if bodyCloseErr != nil {
				logger.Errorf(ctx, "close http body exception => %v", bodyCloseErr)
			}
		}()

		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("invoke http failed, status=%d", resp.StatusCode)
		} else {
			responseBody, err := io.ReadAll(resp.Body)
			if err != nil {
				return err
			}
			err = util.JSONUnmarshal(responseBody, result)
			if err != nil {
				return err
			}
		}
		return nil
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
}

func (r *KlaraHttpImpl) ConcurrentInferEmbedding(ctx context.Context, url rpc.KlaraServiceUrl, inputTexts []string, modelName string) [][]float32 {
	resultChan := make(chan *rpc.KlaraEmbeddingResp, len(inputTexts))
	group := safe_group.NewGroupWithTimeout("KlaraBatchInferEmbedding", 10000).SetLimit(100)

	for idx, inputText := range inputTexts {
		group.Go(func() error {
			request := rpc.KlaraEmbeddingRequest{
				Input: inputText,
				Model: modelName,
			}
			requestBody, _ := json.Marshal(request)
			var result *rpc.KlaraEmbeddingResp
			r.InvokePost(ctx, url, requestBody, &result)
			if result != nil && len(result.Data) > 0 && result.Data[0] != nil {
				result.Data[0].Index = idx
			}
			resultChan <- result
			return nil
		})
	}

	go func() {
		_ = group.Wait()
		close(resultChan)
	}()

	var result []*rpc.KlaraEmbeddingRespItem
	for res := range resultChan {
		if res != nil && len(res.Data) > 0 && res.Data[0] != nil {
			result = append(result, res.Data[0])
		}
	}

	resultIndexMap := lo.GroupBy(result, func(item *rpc.KlaraEmbeddingRespItem) int {
		return item.Index
	})

	// 按位置填充 embeddings，embeddings 的长度与 inputTexts 一致
	var embeddings [][]float32
	for idx := range inputTexts {
		if items, exist := resultIndexMap[idx]; exist {
			embeddings = append(embeddings, items[0].Embedding)
		} else {
			embeddings = append(embeddings, []float32{})
		}
	}

	return embeddings
}

func (r *KlaraHttpImpl) BatchInferPairwiseScoreBySize(ctx context.Context, url rpc.KlaraServiceUrl, request rpc.KlaraRerankRequest, batchSize int) []float32 {
	resultMap := map[string]float32{}
	queryLength := 2048
	textLength := 2048

	query := util.UnicodeSubstr(request.Query, 0, queryLength)

	safe_group.BatchGet(batchSize, request.Texts, func(texts interface{}) interface{} {
		textsInput := texts.([]string)
		output := map[string]float32{}

		body := rpc.KlaraRerankRequest{
			Query: query,
			Texts: lo.Map(textsInput, func(text string, _ int) string {
				return util.UnicodeSubstr(text, 0, textLength)
			}),
		}
		jsonBody, _ := json.Marshal(body)

		var result []*rpc.KlaraRerankRespItem
		r.InvokePost(ctx, url, jsonBody, &result)
		for _, item := range result {
			output[textsInput[item.Index]] = item.Score
		}
		return output
	}, &resultMap)

	result := make([]float32, len(request.Texts))
	for i, text := range request.Texts {
		result[i] = resultMap[text]
	}
	return result
}

func (r *KlaraHttpImpl) statsKlaraRequest(ctx context.Context, startTime time.Time, hasErr bool, statusCode int, url string) {
	isvcName, nameSpace, cluster := util.GetIsvcAndNameSpaceFromKlaraUrl(url)
	level := r.prometheus.CacheGetModelLevel(ctx, isvcName, cluster)

	status := macro.SUCCEED
	if hasErr {
		if ctx.Err() == context.Canceled {
			status = macro.CANCELED
		} else {
			status = macro.FAILED
		}
	}

	// 新
	util.Increment(ctx, macro.KlaraRequestCntStatsFmt, isvcName, nameSpace, status, "0")
	util.Timing(ctx, macro.KlaraRequestTotalTimeStatsFmt, time.Since(startTime), isvcName, nameSpace)

	// 老
	statsd.Increment(fmt.Sprintf(macro.OriginKlaraRequestCntStatsFmt, isvcName, nameSpace, level, status, statusCode))
	statsd.Timing(fmt.Sprintf(macro.OriginKlaraRequestTotalTimeStatsFmt, isvcName, nameSpace, level), time.Since(startTime))
}

func (r *KlaraHttpImpl) formatPrompt(templateType rpc.LLMTemplateType, system string, query string) (string, error) {
	var templateStr string
	switch templateType {
	case rpc.TemplateTypeChatML:
		templateStr = "<|im_start|>system\n{{.System}}<|im_end|>\n<|im_start|>user\n{{.Query}}<|im_end|>\n<|im_start|>assistant\n"
	case rpc.TemplateTypeBaiChuan:
		templateStr = "<reserved_102> {{.Query}}<reserved_102>"
	case rpc.TemplateTypeBaiChuan2:
		templateStr = "<reserved_106> {{.Query}}<reserved_107>"
	case rpc.TemplateTypeChatGLM2:
		templateStr = "[Round 1]\n\n问：{{.Query}}\n\n答： "
	case rpc.TemplateTypeZephyr:
		templateStr = "{{.System}}\n\nUser: {{.Query}}\nAssistant: "
	case rpc.TemplateTypeOpenBuddyLlama:
		templateStr = "<s>[INST] <<SYS>>\n{{.System}}\n<</SYS>>\n\n{{.Query}} [/INST]"
	default:
		templateStr = "{{.System}}\n\n### Human:\n{{.Query}}\n\n### Assistant:\n"
	}

	// 创建一个模板对象并解析模板字符串
	tmpl, err := template.New(string(templateType)).Parse(templateStr)
	if err != nil {
		return "", err
	}
	promptBuffer := &bytes.Buffer{}
	err = tmpl.Execute(promptBuffer, map[string]string{
		"System": system,
		"Query":  query,
	})
	if err != nil {
		return "", err
	}
	return promptBuffer.String(), nil
}
