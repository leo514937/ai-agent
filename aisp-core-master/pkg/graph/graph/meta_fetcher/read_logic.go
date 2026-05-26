package meta_fetcher

import (
	"context"
	"encoding/json"
	"fmt"
	"math/rand"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	basic_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
	"github.com/samber/lo/mutable"
)

// @logicAuthor: wangran
// @logicInfo: read 相关的段落

// ParagraphChunk 段落块结构，用于分块处理
type ParagraphChunk struct {
	Pids []int // 段落ID列表
}

// ChunkResult 分块处理结果
type ChunkResult struct {
	ChunkIndex int
	Pids       []int
	Error      error
}

type ReadResult struct {
	Ranges       []string `json:"ranges"`
	ParagraphIDs []int    `json:"paragraph_ids,omitempty"` // 用于内部存储，不参与JSON序列化
}
type ReadMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]*ReadResult]
	promptService   prompt.PromptMapperService
	modelGatewayRPC modelapi.ModelTarget
	modelName       string
	chunkSize       int // 每个块的最大字符数，默认32768
}

func NewReadMetaFetcherLogic(name string, config map[string]string) *ReadMetaFetcherLogic {
	res := &ReadMetaFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]*ReadResult](name, config),
		chunkSize:    32768, // 默认32768字符
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.promptService = prompt.DefaultPromptMapperService
	res.modelGatewayRPC = rpc.DefaultModelGatewayRouter
	return res
}

var tools = []dto.Tool{
	{
		Type: "function",
		Function: dto.ToolFunction{
			Name:        "select",
			Description: "Select relevant paragraphs or metadata from a document.",
			//Strict:      lo.ToPtr(true),
			Parameters: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"ranges": map[string]interface{}{
						"type":        "array",
						"description": "The id ranges of selected paragraphs, e.g., '1-2' for paragraphs with ids 1 and 2; '1-1' for paragraph with id 1. Set to empty array if no paragraphs are selected.",
						"items": map[string]interface{}{
							"type":    "string",
							"pattern": `(\d+-\d+)`,
						},
						"uniqueItems": true,
					},
				},
				"required": []string{"ranges"},
			},
		},
	},
}

type LogicTracingInput struct {
	OnlyMountDocTokenLength int `json:"only_mount_doc_token_length,omitempty"`
	InputItemCount          int `json:"input_item_count"`
}

func (r *ReadMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]map[string]*ReadResult, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.ReadMetaFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	var resMap = make(map[data_frame.UniqueId]map[string]*ReadResult)
	startTime := time.Now().UnixMilli()

	// todo: 这里改为层次选取
	mutable.Shuffle(items)
	items = items[0:util.Min(len(items), 15)]

	deepSearchContext := requestCtx.GetBizContext().GetDeepSearchContext()
	logicTracingInput := &LogicTracingInput{
		InputItemCount: len(items),
	}

	if r.isPickAllParagraphs(items, deepSearchContext, logicTracingInput) {
		resMap = r.getPickAllParagraphs(items, deepSearchContext.Extract)
		r.saveTracing(logCtx, requestCtx, nil, startTime, logicTracingInput, items, resMap, nil)
		return resMap, nil
	}

	if deepSearchContext.Extract == "" {
		return resMap, nil
	}

	retrievalProducer := requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer().GetOrCreateRoundRetrievalProducer()

	chatConfig := r.getChatConfig(ctx, requestCtx)
	msgConfig := r.getChatMsgConfig(ctx, requestCtx)

	chatConfig = conf.ChatConfig{
		ModelName: "zhida-doubao-seed-1-6-flash",
		TopP:      lo.ToPtr[float32](0.2),
	}
	msgConfig = conf.MsgConfig{
		SystemPromptId: "read_system",
		MsgConfigArr: []conf.ChatMsgConfig{
			conf.NewChatMsgConfigByKnowledge("read_user", "", ""),
		},
	}

	// 使用 safe_group 进行并发控制
	group := safe_group.NewGroupWithTimeout("ReadMetaFetcher", 60000).SetLimit(10) // 设置超时和并发限制
	resultChan := make(chan map[data_frame.UniqueId]map[string]*ReadResult, len(items))
	modelTraceChan := make(chan *ModelTrace)

	// 启动协程消费 modelTraceChan
	var modelTraces []*ModelTrace
	modelTracesDone := make(chan struct{})
	go func() {
		defer close(modelTracesDone)
		var traces []*ModelTrace
		for trace := range modelTraceChan {
			traces = append(traces, trace)
		}
		modelTraces = traces
	}()

	// 启动 goroutines 处理每个内容
	for _, item := range items {
		// 随机 sleep 0-500ms，避免并发过多被误认为异常流量
		time.Sleep(time.Duration(rand.Intn(500)) * time.Millisecond)

		group.Go(func() error {
			defer func() {
				if r := recover(); r != nil {
					log.Warnf(ctx, "Read tool Panic => %v", r)
				}
			}()

			startTime := time.Now()
			result, err := r.RunWithChunks(ctx, deepSearchContext.Extract, item, chatConfig, msgConfig, modelTraceChan)
			log.Infof(ctx, "Read tool Execute => %v, item:%s", time.Since(startTime), item.GetBizItem().ToDescription())
			if err != nil {
				log.Errorf(ctx, "Failed to process content: %v item:%s", err, item.GetBizItem().ToDescription())
			} else if result != nil {
				if readResult, ok := result[deepSearchContext.Extract]; ok && readResult != nil && len(readResult.ParagraphIDs) > 0 {
					cards := item.GetBizItem().ToChatCardByZhiDa()
					retrievalProducer.GetReferenceProducer().Send([]*proto.ChatCard{cards})
				}

				resultChan <- map[data_frame.UniqueId]map[string]*ReadResult{
					*data_frame.NewUniqueId(item.GetCommonItem().Id()): result,
				}
			}
			return nil
		})
	}

	// 等待所有 goroutines 完成
	go func() {
		wgErr := group.Wait()
		if wgErr != nil {
			log.Errorf(ctx, "Read tool Wait Err => %v", wgErr)
		}
		close(resultChan)
		close(modelTraceChan)
	}()

	// 收集结果
	for result := range resultChan {
		for k, v := range result {
			resMap[k] = v
		}
	}

	// 等待 modelTraceChan 消费完成，避免 race condition
	<-modelTracesDone

	r.saveTracing(logCtx, requestCtx, retrievalProducer, startTime, logicTracingInput, items, resMap, modelTraces)
	retrievalProducer.GetReferenceProducer().Done()

	constant.DataOutputNodeLog.Infof(logCtx, "%v", "")
	return resMap, nil
}

func (r *ReadMetaFetcherLogic) isPickAllParagraphs(items []*data_frame.ItemData[entities.Item], deepSearchContext *entities.DeepSearchContext, logicTracingInput *LogicTracingInput) bool {
	if deepSearchContext.SourceType != entities.SourceTypeSpecificDoc {
		return false
	}

	maxTokenLimit := int64(config.GetInt(basic_macro.SpecificDocTokenLimit, 64*1024))
	tokenLength := 0
	for _, item := range items {
		tokenLength += item.GetBizItem().GetItemMeta().Document.GetTokenLength()
	}

	result := int64(tokenLength) <= maxTokenLimit

	logicTracingInput.OnlyMountDocTokenLength = tokenLength

	return result
}

func (r *ReadMetaFetcherLogic) getPickAllParagraphs(items []*data_frame.ItemData[entities.Item], extract string) map[data_frame.UniqueId]map[string]*ReadResult {
	resultMap := make(map[data_frame.UniqueId]map[string]*ReadResult)
	for _, item := range items {
		var paragraphIds []int
		for _, paragraph := range item.GetBizItem().GetItemMeta().Document.Paragraphs {
			paragraphIds = append(paragraphIds, paragraph.ID)
		}
		resultMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = map[string]*ReadResult{
			extract: {ParagraphIDs: paragraphIds},
		}
	}
	return resultMap
}

func (r *ReadMetaFetcherLogic) setPrefixCache(ctx context.Context, item *entities.Item, chunk ParagraphChunk, chatConfig conf.ChatConfig, msgConfig conf.MsgConfig) string {
	systemPrompt, systemErr := r.buildSystemPrompt(ctx, item, chunk, msgConfig.SystemPromptId)

	if systemErr != nil {
		log.Errorf(ctx, "ReadMetaFetcherLogic setPrefixCache error => GenPrompt failed: %v", systemErr)
		return ""
	}

	messages := []*dto.ChatRequestMessage{
		{
			Role:    dto.ChatRequestMessageRoleSystem,
			Content: systemPrompt,
		},
	}

	// 构建 ChatRequest
	chatRequest := &dto.ChatRequest{
		ModelName:  chatConfig.ModelName,
		Messages:   messages,
		Tools:      tools,
		ToolChoice: dto.ToolChoiceOptionsRequired,
		ExtraBody: map[string]interface{}{
			"thinking": map[string]string{"type": "disabled"},
			"caching":  map[string]string{"type": "enabled"},
		},
	}

	// 调用 Responses 接口
	response, err := r.modelGatewayRPC.Responses(ctx, chatRequest)
	if err != nil || response == nil || !strings.HasPrefix(response.ResponseId, "resp_") {
		log.Errorf(ctx, "ModelGatewayRPC.Responses failed: %v", err)
		return ""
	}

	return response.ResponseId
}

func (r *ReadMetaFetcherLogic) buildSystemPrompt(ctx context.Context, item *entities.Item, chunk ParagraphChunk, systemPromptId string) (string, error) {
	systemPrompt, systemErr := r.buildPrompt(ctx, systemPromptId, model.PromptInput{
		DocumentInfo: &model.DocumentPromptInfo{
			DocumentType:    model.GetDocTypeName(item.GetItemMeta().DocType),
			DocumentTitle:   item.GetItemMeta().Document.Title,
			DocumentDate:    item.GetItemMeta().Document.DatePublished,
			DocumentAddDate: item.GetItemMeta().Document.DateAdded,
			DocumentAuthor:  item.GetItemMeta().Document.AuthorName,
			DocumentSources: item.GetItemMeta().Document.Sources,
			DocumentStats:   item.GetItemMeta().Document.Stats,
			Paragraphs:      item.GetItemMeta().Document.Paragraphs,
			DocumentLink:    item.GetItemMeta().Document.URL,
			Pids:            chunk.Pids,
		},
	})

	return systemPrompt, systemErr
}

type ModelTrace struct {
	itemKey     data_frame.UniqueId
	modelInput  *dto.ChatRequest
	modelOutput *dto.ChatResponse
	err         error
}

func (r *ReadMetaFetcherLogic) GetModelResponse(ctx context.Context, specification string, item *data_frame.ItemData[entities.Item], chunk ParagraphChunk, chatConfig conf.ChatConfig, msgConfig conf.MsgConfig, timeout time.Duration, modelTraceChan chan *ModelTrace) (*dto.ChatResponse, error) {
	// 如果没有前缀缓存，那么先构建前缀缓存
	prefixValue, _ := item.GetBizItem().GetItemMeta().PrefixCache.Load(model.AgentRead)
	if prefixValue == nil {
		item.GetBizItem().GetItemMeta().PrefixCache.Store(model.AgentRead, make(map[string]string))
	}
	// 使用更安全的方式构建 pidKey，避免并发问题
	var pidKeys []string
	for _, pid := range chunk.Pids {
		pidKeys = append(pidKeys, strconv.Itoa(pid))
	}
	pidKey := strings.Join(pidKeys, ",")

	// todo: @wangran 临时下线 prefix cache，耗时 badcase 过多，与火山云厂商沟通解决方案 https://zhihu.kdocs.cn/l/cbeHdVmOuX5Q
	//if item.GetItemMeta().PrefixCache[model.AgentRead][pidKey] == "" {
	//	item.GetItemMeta().PrefixCache[model.AgentRead][pidKey] = r.setPrefixCache(ctx, item, chunk, chatConfig, msgConfig)
	//}

	systemPrompt, systemErr := r.buildSystemPrompt(ctx, item.GetBizItem(), chunk, msgConfig.SystemPromptId)

	userPrompt, userErr := r.buildPrompt(ctx, msgConfig.MsgConfigArr[0].PromptId, model.PromptInput{
		Specification: specification,
	})

	if systemErr != nil || userErr != nil || systemPrompt == "" || userPrompt == "" {
		log.Errorf(ctx, "ReadMetaFetcherLogic GetModelResponse error => buildPrompt failed: systemErr: %v, userErr: %v", systemErr, userErr)
		return nil, fmt.Errorf("buildPrompt failed")
	}

	// 构建消息
	messages := []*dto.ChatRequestMessage{
		{
			Role:    dto.ChatRequestMessageRoleUser,
			Content: userPrompt,
		},
	}

	// 构建 ChatRequest
	chatReq := &dto.ChatRequest{
		ModelName: chatConfig.ModelName,
		Messages:  messages,
		ExtraBody: map[string]interface{}{
			"thinking": map[string]string{"type": "disabled"},
		},
		Temperature: lo.ToPtr[float32](0.0),
	}

	// 如果有前缀缓存，设置 PreviousResponseId
	if prefixValue, ok := item.GetBizItem().GetItemMeta().PrefixCache.Load(model.AgentRead); ok {
		if prefixMap, ok := prefixValue.(map[string]string); ok {
			if responseId, exists := prefixMap[pidKey]; exists && responseId != "" {
				chatReq.PreviousResponseId = responseId
			}
		}
	}

	if chatReq.PreviousResponseId == "" {
		// 如果没有前缀缓存，降级为正常请求
		chatReq.Messages = append([]*dto.ChatRequestMessage{{
			Role:    dto.ChatRequestMessageRoleSystem,
			Content: systemPrompt,
		}}, messages...)
		chatReq.Tools = tools
		chatReq.FunctionTool = tools[0].Function.Name
		chatReq.ExtraBody["store"] = false
	}

	newCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	util2.Increment(ctx, basic_macro.CommonStatsPrefix+".deepsearch.read_model.count")

	startTime := time.Now()
	response, err := r.modelGatewayRPC.Responses(newCtx, chatReq)
	log.Infof(ctx, "Read Responses Execute => %v", time.Since(startTime))

	modelTraceChan <- &ModelTrace{
		itemKey:     *data_frame.NewUniqueId(item.GetCommonItem().Id()),
		modelInput:  chatReq,
		modelOutput: response,
		err:         err,
	}
	if err != nil {
		log.Errorf(ctx, "ModelGatewayRPC.Responses failed: %v", err)
		return nil, err
	}

	return response, nil
}

func (r *ReadMetaFetcherLogic) buildPrompt(ctx context.Context, promptKey string, promptInput model.PromptInput) (string, error) {
	promptTemp := r.promptService.LoadPromptByApollo(ctx, promptKey, "", "", 0)
	promptContent, err := model.GenPrompt(&promptInput, promptTemp, promptKey)
	if err != nil {
		log.Errorf(ctx, "QueryRouterLogic buildPrompt template parse error: %+v", err)
		return "", nil
	}

	return promptContent, nil
}

// splitParagraphsIntoChunks 将段落按照字符数拆分成块
func (r *ReadMetaFetcherLogic) splitParagraphsIntoChunks(document *model.Document) []ParagraphChunk {
	var chunks []ParagraphChunk
	var currentChunk ParagraphChunk
	currentChunkSize := 0

	for _, paragraph := range document.Paragraphs {
		paragraphSize := util2.UnicodeLen(paragraph.Content)
		if paragraphSize > r.chunkSize {
			continue
		}

		// 如果当前块加上新段落会超过限制，先保存当前块
		if currentChunkSize+paragraphSize > r.chunkSize && len(currentChunk.Pids) > 0 {
			chunks = append(chunks, currentChunk)
			currentChunk = ParagraphChunk{
				Pids: []int{},
			}
			currentChunkSize = 0
		}

		// 添加当前段落到块中
		currentChunk.Pids = append(currentChunk.Pids, paragraph.ID)
		currentChunkSize += paragraphSize
	}

	// 添加最后一个块
	if len(currentChunk.Pids) > 0 {
		chunks = append(chunks, currentChunk)
	}

	return chunks
}

// RunWithChunks 运行阅读理解工具 - 支持分块并发处理
func (r *ReadMetaFetcherLogic) RunWithChunks(ctx context.Context, specification string, item *data_frame.ItemData[entities.Item], chatConfig conf.ChatConfig, msgConfig conf.MsgConfig, modelTraceChan chan *ModelTrace) (map[string]*ReadResult, error) {
	document := item.GetBizItem().GetItemMeta().Document
	if document == nil || len(document.Paragraphs) == 0 {
		return nil, fmt.Errorf("document or paragraphs is empty")
	}

	util2.Increment(ctx, basic_macro.CommonStatsPrefix+".deepsearch.read_item.count")

	// 将段落分块
	chunks := r.splitParagraphsIntoChunks(document)
	if len(chunks) == 0 {
		return nil, fmt.Errorf("no chunks created")
	}

	log.Infof(ctx, "Document split into %d chunks for processing", len(chunks))

	// 使用channel收集结果，避免并发写入slice
	resultChan := make(chan ChunkResult, len(chunks))

	// 使用 safe_group 控制并发数
	group := safe_group.NewGroupWithTimeout("ChunkProcessing", 5000).SetLimit(2)

	for i, chunk := range chunks {
		group.Go(func() error {
			defer func() {
				if r := recover(); r != nil {
					log.Warnf(ctx, "Chunk processing panic: %v", r)
				}
			}()

			pids, err := r.processChunk(ctx, specification, item, chunk, chatConfig, msgConfig, 4*time.Second, modelTraceChan)
			resultChan <- ChunkResult{
				ChunkIndex: i,
				Pids:       pids,
				Error:      err,
			}
			return err
		})
	}

	// 等待所有块处理完成
	go func() {
		group.Wait()
		close(resultChan)
	}()

	// 收集所有结果
	var results []ChunkResult
	for result := range resultChan {
		results = append(results, result)
	}

	if len(results) == 0 {
		return nil, nil
	}

	var originParagraphCount []*model.DocumentParagraph
	if item.GetBizItem().GetItemMeta().ReadParagraphs != nil {
		originParagraphCount = item.GetBizItem().GetItemMeta().ReadParagraphs[specification]
	}
	// 合并结果
	return r.mergeChunkResults(specification, results, originParagraphCount)
}

// processChunk 处理单个块 - 简化版本，由prompt选择pid
func (r *ReadMetaFetcherLogic) processChunk(ctx context.Context, specification string, item *data_frame.ItemData[entities.Item], chunk ParagraphChunk, chatConfig conf.ChatConfig, msgConfig conf.MsgConfig, modelTimeout time.Duration, modelTraceChan chan *ModelTrace) ([]int, error) {
	const maxRetries = 1 // 先关了，目前 retry 必导致外层超时

	for attempt := 0; attempt < maxRetries; attempt++ {
		// 调用 LLM
		response, err := r.GetModelResponse(ctx, specification, item, chunk, chatConfig, msgConfig, modelTimeout, modelTraceChan)
		if err != nil {
			log.Warnf(ctx, "Attempt %d failed, retrying: %v", attempt+1, err)
			continue
		}

		// 校验返回值的合法性
		if !response.IsValidFunctionCallResponse(ReadResult{}) {
			continue
		}

		// 解析返回值
		var readResp ReadResult
		if err := json.Unmarshal([]byte(response.FunctionCallResults[0].Arguments), &readResp); err != nil {
			log.Warnf(ctx, "Attempt %d failed to parse JSON, retrying: %v", attempt+1, err)
			continue
		}

		// 解析范围字符串为段落ID列表
		document := item.GetBizItem().GetItemMeta().Document
		allParagraphIDs := r.parseRanges(readResp.Ranges, document)

		// 验证段落ID是否在有效范围内（当前块的段落ID）
		var validPids []int
		for _, pid := range allParagraphIDs {
			// 检查pid是否在当前块的段落中
			for _, chunkPid := range chunk.Pids {
				if pid == chunkPid {
					validPids = append(validPids, pid)
					break
				}
			}
		}

		sort.Ints(validPids)
		return validPids, nil
	}

	// 如果所有重试都失败了，返回最后一个错误
	return nil, fmt.Errorf("failed after %d attempts", maxRetries)
}

// mergeChunkResults 合并多个块的处理结果
func (r *ReadMetaFetcherLogic) mergeChunkResults(intent string, results []ChunkResult, originParagraph []*model.DocumentParagraph) (map[string]*ReadResult, error) {
	result := make(map[string]*ReadResult)

	// 按chunk顺序合并结果
	mergedPids := make(map[string][]int)

	// item 上一些轮次的 intent 下读取的段落
	for _, paragraph := range originParagraph {
		mergedPids[intent] = append(mergedPids[intent], paragraph.ID)
	}
	// 当前轮次的 intent 下读取的段落
	for _, chunkResult := range results {
		if chunkResult.Error != nil {
			log.Warnf(context.Background(), "Chunk %d processing failed: %v", chunkResult.ChunkIndex, chunkResult.Error)
			continue
		}
		mergedPids[intent] = append(mergedPids[intent], chunkResult.Pids...)
	}

	// 对每个intent的段落ID去重并排序
	for currentIntent, pids := range mergedPids {
		// 去重
		pidMap := make(map[int]bool)
		var uniquePids []int
		for _, pid := range pids {
			if !pidMap[pid] {
				pidMap[pid] = true
				uniquePids = append(uniquePids, pid)
			}
		}

		// 排序
		sort.Ints(uniquePids)
		mergedPids[currentIntent] = uniquePids
	}

	result[intent] = &ReadResult{
		ParagraphIDs: mergedPids[intent],
	}

	return result, nil
}

func (r *ReadMetaFetcherLogic) getChatConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.ChatConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if configStr == "" {
		log.Errorf(ctx, "ReadMetaFetcherLogic getChatConfig error => config is empty")
		return conf.ChatConfig{}
	}

	chatConfig := conf.ChatConfig{}
	err := json.Unmarshal([]byte(configStr), &chatConfig)
	if err != nil {
		log.Errorf(ctx, "ReadMetaFetcherLogic getChatConfig error => config is json unmarshal err")
		return conf.ChatConfig{}
	}
	return chatConfig
}

func (r *ReadMetaFetcherLogic) getChatMsgConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.MsgConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.ChatMessageJsonConfig)
	if configStr == "" {
		log.Errorf(ctx, "ReadMetaFetcherLogic getChatMsgConfig error => config is empty")
		return conf.MsgConfig{}
	}

	chatMsgConfig := conf.MsgConfig{}
	err := json.Unmarshal([]byte(configStr), &chatMsgConfig)
	if err != nil {
		log.Errorf(ctx, "ReadMetaFetcherLogic getChatMsgConfig error => config is json unmarshal err")
	}
	return chatMsgConfig
}

func (r *ReadMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res map[string]*ReadResult) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.TagCoreMetaFetcherLogic.itemMerge")
	defer span.Finish()

	readParagraphs := map[string][]*model.DocumentParagraph{}
	for intent, readResult := range res {
		for _, pid := range readResult.ParagraphIDs {
			if item.GetBizItem().GetItemMeta().Document != nil {
				for _, paragraph := range item.GetBizItem().GetItemMeta().Document.Paragraphs {
					if paragraph.ID == pid {
						if _, exist := readParagraphs[intent]; !exist {
							readParagraphs[intent] = []*model.DocumentParagraph{}
						}
						readParagraphs[intent] = append(readParagraphs[intent], paragraph)
						break
					}
				}
			}
		}
	}

	item.GetBizItem().GetItemMeta().ReadParagraphs = readParagraphs
	return nil
}

// parseRanges 解析范围字符串，返回段落ID列表。ranges 的输入可能为["0-2"]也可能为["0","1","2"]
func (r *ReadMetaFetcherLogic) parseRanges(ranges []string, document *model.Document) []int {
	paragraphIDs := make(map[int]bool)

	if len(ranges) == 0 {
		return []int{}
	}

	for _, rangeStr := range ranges {
		// 检查是否为范围格式 "数字-数字"
		rangeRe := regexp.MustCompile(`^(\d+)-(\d+)$`)
		rangeMatches := rangeRe.FindStringSubmatch(rangeStr)

		if len(rangeMatches) == 3 {
			// 处理范围格式
			start, err1 := strconv.Atoi(rangeMatches[1])
			end, err2 := strconv.Atoi(rangeMatches[2])

			if err1 != nil || err2 != nil {
				continue
			}

			// 确保 start <= end
			if start > end {
				continue
			}

			// 添加范围内的所有ID
			for i := start; i <= end; i++ {
				paragraphIDs[i] = true
			}
		} else {
			// 处理单值格式 "数字"
			singleRe := regexp.MustCompile(`^(\d+)$`)
			singleMatches := singleRe.FindStringSubmatch(rangeStr)

			if len(singleMatches) == 2 {
				id, err := strconv.Atoi(singleMatches[1])
				if err == nil {
					paragraphIDs[id] = true
				}
			}
		}
	}

	// 过滤有效的段落ID（在文档段落范围内）
	var validIDs []int
	for id := range paragraphIDs {
		if id >= 0 && id < len(document.Paragraphs) {
			validIDs = append(validIDs, id)
		}
	}

	// 排序并返回
	sort.Ints(validIDs)
	return validIDs
}

func (r *ReadMetaFetcherLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], retrievalProducer *chat_event.RetrievalEvent, startTime int64,
	logicTracingInput *LogicTracingInput, inputItems []*data_frame.ItemData[entities.Item], resMap map[data_frame.UniqueId]map[string]*ReadResult, modelTraces []*ModelTrace) {

	modelTraceMap := make(map[data_frame.UniqueId]map[string]string)
	for _, trace := range modelTraces {
		if trace == nil {
			continue
		}

		var input, output string

		// Encode modelInput with panic protection
		func() {
			defer func() {
				if r := recover(); r != nil {
					input = fmt.Sprintf(`{"error": "json encoding panic: %v"}`, r)
					log.Errorf(logCtx, "JSON encoding panic for modelInput: %v", r)
				}
			}()

			if trace.modelInput != nil {
				input = util2.SafeTruncateJSON(util.GetJSONIgnoreError(trace.modelInput), 512)
			} else {
				input = "null"
			}
		}()

		// Encode modelOutput with panic protection
		func() {
			defer func() {
				if r := recover(); r != nil {
					output = fmt.Sprintf(`{"error": "json encoding panic: %v"}`, r)
					log.Errorf(logCtx, "JSON encoding panic for modelOutput: %v", r)
				}
			}()

			if trace.modelOutput != nil {
				output = util2.SafeTruncateJSON(util.GetJSONIgnoreError(trace.modelOutput), 256)
			} else {
				output = "null"
			}
		}()

		modelTraceMap[trace.itemKey] = map[string]string{
			"input":  input,
			"output": output,
			"error":  fmt.Sprint(trace.err),
		}
	}

	outputMap := make(map[string]interface{})
	for _, inputItem := range inputItems {
		uniqueKey := *data_frame.NewUniqueId(inputItem.GetCommonItem().Id())

		var docIdentity string
		if inputItem.GetBizItem().GetItemMeta().DocId != 0 {
			docIdentity = fmt.Sprintf("%s-%d", inputItem.GetBizItem().GetItemMeta().DocType.String(), inputItem.GetBizItem().GetItemMeta().DocId)
		} else {
			docIdentity = fmt.Sprintf("%s-%s", inputItem.GetBizItem().GetItemMeta().DocType.String(), inputItem.GetBizItem().GetItemMeta().Url)
		}

		// 最终返回结果
		resultMap := make(map[string][]int)
		if result, exist := resMap[uniqueKey]; exist {
			for extract, paragraphs := range result {
				resultMap[extract] = paragraphs.ParagraphIDs
			}
		}
		// 模型调用结果
		var modelTrace = modelTraceMap[uniqueKey]

		// 将以上结果存入 outputMap
		outputMap[docIdentity] = map[string]interface{}{
			"result":     resultMap,
			"modelTrace": modelTrace,
		}
	}

	logicTracing := &proto.LogicTracing{
		LogicName:   r.GetName(),
		LogicInput:  []string{util.GetJSONIgnoreError(logicTracingInput)},
		LogicOutput: []string{util.GetJSONIgnoreError(outputMap)},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(fmt.Sprintf("%s-%d", r.GetName(), time.Now().Unix()), logicTracing)

	if retrievalProducer != nil {
		retrievalProducer.GetReferenceProducer().Tracing(util.GetJSONIgnoreError(map[string]interface{}{
			"input":  logicTracingInput,
			"output": outputMap,
		}))
	}

}
