package root_logic

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand"
	"sort"
	"strings"
	"sync"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	basic_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/req_macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/sub_graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 直答 agent deepsearch 召回
type DeepSearchLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	deepSearchRecallService *sub_graph.DeepSearchService
	modelGatewayRPC         modelapi.ModelTarget
	promptService           prompt.PromptMapperService
	riskClient              rpc.RiskCheckRPC
}

func NewDeepSearchLogic(name string, config map[string]string) *DeepSearchLogic {
	res := &DeepSearchLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
		deepSearchRecallService:  sub_graph.NewDeepSearchService(),
		modelGatewayRPC:          rpc.DefaultModelGatewayRouter,
		promptService:            prompt.DefaultPromptMapperService,
		riskClient:               rpcImpl.NewRiskCheckRPCImpl(),
	}

	res.RecallFunc = res.recall
	return res
}

// ToolCall 工具调用结构
type ToolCall struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments"`
}

// SearchToolArgs 搜索工具参数
type SearchToolArgs struct {
	Goal    string   `json:"goal"`
	Extract string   `json:"content_topic"`
	Queries []string `json:"queries"`
	Sources []string `json:"sources"`
}

// BrowseToolArgs 浏览工具参数
type BrowseToolArgs struct {
	Goal     string `json:"goal"`
	Extract  string `json:"content_role"`
	Priority string `json:"subset"`
	Source   string `json:"source"`
}

// SelectToolArgs 选择工具参数
type SelectToolArgs struct {
	ContentIDs []int `json:"document_ids"`
}

// 工具定义
var (
	baseSearchTool = dto.Tool{
		Type: "function",
		Function: dto.ToolFunction{
			Name:        "search",
			Description: "Search documents from given sources by matching queries against document content. Default choice for document curation.",
			Parameters: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"goal": map[string]interface{}{
						"type":        "string",
						"description": "a concise, self-contained 中文 statement of information to be sought",
					},
					"sources": map[string]interface{}{
						"type":        "array",
						"items":       map[string]interface{}{"type": "string"},
						"description": "list of sources to search documents from",
					},
					"queries": map[string]interface{}{
						"type":        "array",
						"items":       map[string]interface{}{"type": "string"},
						"description": "queries to match against content of documents (max 3): use minimal, specific and varied keywords for each query to maximize coverage; order queries by importance to the goal; match the language of user requests or requirements in source descriptions",
					},
					"content_topic": map[string]interface{}{
						"type":        "string",
						"description": "concise statement of the topic of content to extract from each document",
					},
				},
				"required": []string{"goal", "sources", "queries", "content_topic"},
			},
		},
	}

	baseBrowseTool = dto.Tool{
		Type: "function",
		Function: dto.ToolFunction{
			Name:        "browse",
			Description: "Retrieve a subset of documents from the given source. Use when no search queries can be inferred from the goal, or you need to refer to content by its role within documents.",
			Parameters: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"goal": map[string]interface{}{
						"type":        "string",
						"description": "a concise, self-contained 中文 statement of information to be sought",
					},
					"source": map[string]interface{}{
						"description": "source to retrieve documents from",
					},
					"subset": map[string]interface{}{
						"enum":        []string{"recent", "best", "random", "all"},
						"description": "types of documents subset: 'recent' for 10 recently added documents, 'best' for 10 highest-rated documents, 'random' for 10 representative sampling of the source, 'all' for all documents",
					},
					"content_role": map[string]interface{}{
						"type":        "string",
						"description": "concise description of the role of content to extract from the document to, e.g., structural role like '文档的摘要', '文档的参考文献'; semantic role like '文档的核心观点', '文档的主要内容'; metadata like '文档的作者', '文档的发布日期'; for features of content like style, tone or rhetoric, extract the main content with '文档的主要内容' for later inference.",
					},
				},
				"required": []string{"goal", "source", "subset", "content_role"},
			},
		},
	}

	baseSelectTool = dto.Tool{
		Type: "function",
		Function: dto.ToolFunction{
			Name:        "select",
			Description: "Select documents as references.",
			Parameters: map[string]interface{}{
				"type": "object",
				"properties": map[string]interface{}{
					"document_ids": map[string]interface{}{
						"type":        "array",
						"items":       map[string]interface{}{"type": "integer"},
						"description": "ids of documents ordered by credibility and relevance",
					},
				},
				"required": []string{"document_ids"},
			},
		},
	}
)

const (
	maxRounds = 10
	maxRetry  = 2
)

type ModelTrace struct {
	ModelInput  *dto.ChatRequest  `json:"model_input"`
	ModelOutput *dto.ChatResponse `json:"model_output"`
	Err         error             `json:"error"`
	TimeCost    string            `json:"time_cost"`
}

func (d *DeepSearchLogic) recall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	resList := make([]*data_frame.ItemData[entities.Item], 0)

	util.Increment(ctx, basic_macro.CommonStatsPrefix+".deepsearch.root.count")

	requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer()
	defer requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer().Done()

	// 获取数据源映射
	sourceMap := genSourceMap(requestCtx.GetBizContext().GetSearchSourceMap())

	if sourceMap == nil || len(sourceMap) == 0 {
		return resList, nil
	}

	if isOnlyMountDocs(sourceMap) {
		mountDocSourceNames := getMountDocSourceNames(sourceMap)
		references, err := d.handleMountDocs(ctx, requestCtx, mountDocSourceNames)
		if err == nil && len(references) > 0 {
			summary, err := d.genFinalSummary(ctx, references)
			requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer().Tracing(util.GetJSONIgnoreError(map[string]interface{}{
				"model":   "Pure mounting does not require calling models",
				"message": util.UnicodeSubstr(summary, 0, 1024),
				"items": lo.Map(references, func(item *data_frame.ItemData[entities.Item], _ int) string {
					return item.GetBizItem().ToDescription()
				}),
			}))
			if err == nil {
				d.setDeepResearchSummaryMessage(requestCtx, summary)
				return references, err
			} else {
				log.Errorf(ctx, "Failed to render reference template: %v", err)
			}
		} else {
			log.Errorf(ctx, "HandleMountDocs err: %v, len(references):%d", err, len(references))
		}
	}

	// 构建 systemPrompt
	systemPrompt, err := d.buildSystemPrompt(ctx, sourceMap)
	if err != nil {
		log.Errorf(ctx, "Failed to build system prompt: %v", err)
		return resList, err
	}

	// 对输入的 message 深拷贝，避免影响主体循环
	var messages = util.DeepCopy(requestCtx.GetBizContext().GetMessages()).([]*dto.ChatRequestMessage)

	// 替换 messages 首位的 systemPrompt
	if len(messages) > 0 && messages[0].Role == dto.ChatRequestMessageRoleSystem {
		messages = messages[1:]
	}
	messages = append([]*dto.ChatRequestMessage{
		{
			Role:    dto.ChatRequestMessageRoleSystem,
			Content: systemPrompt,
		},
	}, messages...)

	// 存储研究历史和目标
	var references []*data_frame.ItemData[entities.Item]
	retry := 0
	var goals []string

	tools := genTools(sourceMap)

	var modelTraces []*ModelTrace

	// 开始研究循环
	for round := 1; round < maxRounds; round++ {
		log.Infof(ctx, "DeepSearch round %d, deciding...", round)
		util.Increment(ctx, basic_macro.CommonStatsPrefix+".deepsearch.round.count")
		start := time.Now()

		researchRouterChatReq := &dto.ChatRequest{
			ModelName:  "zhida-kimi-k2",
			Messages:   messages,
			Tools:      tools,
			ToolChoice: dto.ToolChoiceOptionsRequired,
			TopP:       lo.ToPtr[float32](0.0),
		}
		// 调用模型选择工具
		response, err := d.modelGatewayRPC.Chat(ctx, researchRouterChatReq)
		modelTraces = append(modelTraces, &ModelTrace{
			ModelInput:  researchRouterChatReq,
			ModelOutput: response,
			Err:         err,
			TimeCost:    time.Since(start).String(),
		})

		if err != nil || response == nil {
			continue
		}

		for _, toolCall := range response.FunctionCallResults {
			// 处理不同的工具调用
			switch toolCall.Name {
			case "select":
				util.Increment(ctx, basic_macro.CommonStatsPrefix+".deepsearch.select.count")

				// toolCall.Arguments 反序列化到 SelectToolArgs 上
				selectArgs := &SelectToolArgs{}
				unmarshalErr := json.Unmarshal([]byte(toolCall.Arguments), &selectArgs)
				if unmarshalErr != nil {
					continue
				}
				result, summary, err := d.handleSelectTool(ctx, goals, references, selectArgs, modelTraces, requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer())
				d.setDeepResearchSummaryMessage(requestCtx, summary)

				return result, err
			case "search":
				util.Increment(ctx, basic_macro.CommonStatsPrefix+".deepsearch.search.count")

				searchArgs := &SearchToolArgs{}
				unmarshalErr := json.Unmarshal([]byte(toolCall.Arguments), &searchArgs)
				if unmarshalErr != nil {
					continue
				}
				// 校验返回值的合法性
				if !response.IsValidFunctionCallResponse(SearchToolArgs{}) {
					continue
				}

				// 安全审核 goal
				if !d.riskCheckGoalOrSummary(ctx, requestCtx.GetBizContext().MemberId(), requestCtx.GetBizContext().MessageId(), searchArgs.Goal, "") {
					continue
				}
				// 安全审核 queries
				searchArgs.Queries = d.riskCheckQueries(ctx, requestCtx.GetBizContext().MemberId(), requestCtx.GetBizContext().MessageId(), searchArgs.Queries)
				if len(searchArgs.Queries) == 0 {
					continue
				}
				// 安全通过以后，发 event
				retrievalProducer := requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer().GetOrCreateRoundRetrievalProducer()
				retrievalProducer.GetTopicProducer().Send(&chat_event.TopicContent{
					Topic:         searchArgs.Goal,
					RetrievalType: chat_event.RtSearch,
					SourceInfos:   getHitSourceInfo(sourceMap, searchArgs.Sources),
				}).Tracing(util.GetJSONIgnoreError(researchRouterChatReq)).Done()
				retrievalProducer.GetKeywordsProducer().Send(searchArgs.Queries).Done()

				candidates, err := d.handleSearchTool(ctx, requestCtx, references, searchArgs)
				util.TimingInMilSec(ctx, basic_macro.CommonStatsPrefix+".deepsearch.search_retrieval.count", float64(len(candidates)))

				if err != nil || len(candidates) == 0 {
					log.Errorf(ctx, "Search tool failed: %v", err)
					retry++
					if retry > maxRetry {
						result, summary, err := d.forceSelect(ctx, goals, references, messages, tools, modelTraces, requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer())
						d.setDeepResearchSummaryMessage(requestCtx, summary)
						retrievalProducer.ProducerDone()
						return result, err
					}
				}

				// 添加到引用列表
				references = lo.Uniq(append(references, candidates...))
				// 生成摘要
				digestContent, securityFlag := d.genDigestContent(ctx,
					requestCtx.GetBizContext().MemberId(), requestCtx.GetBizContext().MessageId(),
					searchArgs.Goal, searchArgs.Extract, candidates, retrievalProducer)

				// 关闭 retrievalProducer
				retrievalProducer.ProducerDone()
				if securityFlag {
					digestMessage := d.genDigestMessage(ctx, digestContent, references, candidates)
					goals = append(goals, searchArgs.Goal)
					messages = append(messages, d.genDeepsearchInternalMessages(toolCall, digestMessage)...)
				}
			case "browse":
				util.Increment(ctx, basic_macro.CommonStatsPrefix+".deepsearch.browse.count")

				browseArgs := &BrowseToolArgs{}
				unmarshalErr := json.Unmarshal([]byte(toolCall.Arguments), &browseArgs)
				if unmarshalErr != nil {
					continue
				}

				// 校验返回值的合法性
				if !response.IsValidFunctionCallResponse(BrowseToolArgs{}) {
					continue
				}

				// 安全审核 goal
				if !d.riskCheckGoalOrSummary(ctx, requestCtx.GetBizContext().MemberId(), requestCtx.GetBizContext().MessageId(), browseArgs.Goal, "") {
					continue
				}
				// 安全通过以后，发 event
				retrievalProducer := requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer().GetOrCreateRoundRetrievalProducer()
				retrievalProducer.GetTopicProducer().Send(&chat_event.TopicContent{
					Topic:         browseArgs.Goal,
					RetrievalType: chat_event.RtBrowse,
					SourceInfos:   getHitSourceInfo(sourceMap, []string{browseArgs.Source}),
				}).Done()

				candidates, err := d.handleBrowseTool(ctx, requestCtx, references, browseArgs)
				util.TimingInMilSec(ctx, basic_macro.CommonStatsPrefix+".deepsearch.browse_retrieval.count", float64(len(candidates)))

				if err != nil || len(candidates) == 0 {
					log.Errorf(ctx, "Search tool failed: %v", err)
					retry++
					if retry > maxRetry {
						result, summary, err := d.forceSelect(ctx, goals, references, messages, tools, modelTraces, requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer())
						d.setDeepResearchSummaryMessage(requestCtx, summary)
						retrievalProducer.ProducerDone()
						return result, err
					}
				}

				// 添加到引用列表
				references = lo.Uniq(append(references, candidates...))

				// 生成摘要
				digestContent, securityFlag := d.genDigestContent(ctx,
					requestCtx.GetBizContext().MemberId(), requestCtx.GetBizContext().MessageId(),
					browseArgs.Goal, browseArgs.Extract, candidates, retrievalProducer)

				// 关闭 retrievalProducer
				retrievalProducer.ProducerDone()
				if securityFlag {
					digestMessage := d.genDigestMessage(ctx, digestContent, references, candidates)
					goals = append(goals, browseArgs.Goal)
					messages = append(messages, d.genDeepsearchInternalMessages(toolCall, digestMessage)...)
				}
			default:
				log.Errorf(ctx, "Unknown tool: %s", toolCall.Name)
				continue
			}
		}
	}

	// 达到循环上限，强制选择
	log.Infof(ctx, "Reached max rounds, forcing select")
	result, summary, err := d.forceSelect(ctx, goals, references, messages, tools, modelTraces, requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer())
	d.setDeepResearchSummaryMessage(requestCtx, summary)
	return result, err
}

func getHitSourceInfo(sourceMap map[string]*req_macro.SourceInfo, sourceName []string) []*req_macro.SourceInfo {
	var result []*req_macro.SourceInfo
	for _, name := range sourceName {
		if info, ok := sourceMap[name]; ok && info != nil {
			result = append(result, info)
		}
	}
	return result
}

func (d *DeepSearchLogic) genDigestContent(ctx context.Context,
	memberId int64,
	messageId string,
	goal string,
	extract string,
	candidates []*data_frame.ItemData[entities.Item],
	retrievalEvent *chat_event.RetrievalEvent) (string, bool) {

	securityFlag := true
	var digestProducer chat_event.EventProducer[*chat_event.AnswerContent]
	if retrievalEvent != nil {
		digestProducer = retrievalEvent.GetAnswerProducer()
	}
	defer func() {
		if digestProducer != nil {
			digestProducer.Done()
		}
	}()

	lastDigestContent := ""
	if len(candidates) == 0 {
		if digestProducer != nil {
			digestProducer.Tracing("Candidates is empty")
		}
		lastDigestContent = "未找到相关信息"
	} else {
		lastDigestContent = d.digestTool(ctx, goal, extract, candidates, digestProducer)
	}

	// 安全审核 digest(如果异常 则额外发送一次 respType)
	if !d.riskCheckGoalOrSummary(ctx, memberId, messageId, "", lastDigestContent) {
		securityFlag = false
		if digestProducer != nil {
			digestProducer.Send(&chat_event.AnswerContent{Content: "", ChatRespType: proto.ChatRespType_REFUSE})
		}
	}

	return lastDigestContent, securityFlag
}

func (d *DeepSearchLogic) genDeepsearchInternalMessages(toolCall dto.FunctionCallResult, digestMessage string) []*dto.ChatRequestMessage {
	return []*dto.ChatRequestMessage{
		{
			Role:       dto.ChatRequestMessageRoleToolInPut,
			Content:    toolCall.Arguments,
			ToolCallId: toolCall.ID,
			Name:       toolCall.Name,
		},
		{
			Role:       dto.ChatRequestMessageRoleToolOutPut,
			Content:    digestMessage,
			ToolCallId: toolCall.ID,
			Name:       toolCall.Name,
		},
	}
}

func (d *DeepSearchLogic) setDeepResearchSummaryMessage(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], summary string) {
	if summary == "" {
		return
	}
	requestCtx.GetBizContext().AddMessages(&dto.ChatRequestMessage{
		Role:    dto.ChatRequestMessageRoleAI,
		Content: util.GetJSONIgnoreError(requestCtx.GetBizContext().GetToolInfo()),
	})
	requestCtx.GetBizContext().AddMessages(&dto.ChatRequestMessage{
		Name:       macro.RouterAgentByResearch.String(),
		ToolCallId: requestCtx.GetBizContext().GetToolInfo().ID,
		Role:       dto.ChatRequestMessageRoleToolOutPut,
		Content:    summary,
	})
}

func (d *DeepSearchLogic) forceSelect(ctx context.Context, goals []string,
	references []*data_frame.ItemData[entities.Item], messages []*dto.ChatRequestMessage, tools []dto.Tool, modelTraces []*ModelTrace, retrievalProducer *chat_event.ChatEventByRetrievalProducer) ([]*data_frame.ItemData[entities.Item], string, error) {
	// 调用模型选择工具
	response, err := d.modelGatewayRPC.Chat(ctx, &dto.ChatRequest{
		ModelName:    "zhida-kimi-k2",
		Messages:     messages,
		Tools:        tools,
		FunctionTool: "select",
	})

	if err != nil || response == nil || len(response.FunctionCallResults) == 0 {
		log.Errorf(ctx, "Model response err: %v, or no FunctionCallResults", err)
		return d.handleSelectTool(ctx, goals, references, nil, modelTraces, retrievalProducer)
	}

	selectArgsStr := ""
	for _, toolCall := range response.FunctionCallResults {
		if toolCall.Name == "select" {
			selectArgsStr = toolCall.Arguments
			break
		}
	}

	selectArgs := &SelectToolArgs{}
	_ = json.Unmarshal([]byte(selectArgsStr), &selectArgs)
	return d.handleSelectTool(ctx, goals, references, selectArgs, modelTraces, retrievalProducer)
}

func (d *DeepSearchLogic) buildSystemPrompt(ctx context.Context, sourceMap map[string]*req_macro.SourceInfo) (string, error) {
	promptInput := struct {
		SourceMap map[string]*req_macro.SourceInfo `json:"source_map"`
	}{
		SourceMap: sourceMap,
	}

	promptContent, err := d.promptService.BuildPromptWithApollo(ctx, "deepsearch_toolchoice", "", "", 0, promptInput)
	if err != nil {
		log.Errorf(ctx, "Failed to build system prompt: %v", err)
		return "", err
	}

	return promptContent, nil
}

func (d *DeepSearchLogic) handleMountDocs(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], sourcesName []string) ([]*data_frame.ItemData[entities.Item], error) {
	resList := make([]*data_frame.ItemData[entities.Item], 0)

	requestCtx.GetBizContext().SetDeepSearchContext(&entities.DeepSearchContext{
		RetrievalType: proto.RetrievalType_RT_BROWSE,
		SourcesName:   sourcesName,
		SourceType:    entities.SourceTypeSpecificDoc,
	})

	recallItems, err := d.deepSearchRecallService.Recall(ctx, requestCtx)

	for i, item := range recallItems {
		item.GetItemMeta().Index = i + 1
	}
	if err != nil {
		return resList, err
	}

	return recallItemToResultItemList(requestCtx, recallItems), nil
}

// handleSearchTool 处理搜索工具
func (d *DeepSearchLogic) handleSearchTool(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	lastRoundItems []*data_frame.ItemData[entities.Item], searchArgs *SearchToolArgs) ([]*data_frame.ItemData[entities.Item], error) {
	log.Infof(ctx, "Executing search tool...")

	resList := make([]*data_frame.ItemData[entities.Item], 0)

	requestCtx.GetBizContext().SetDeepSearchContext(&entities.DeepSearchContext{
		RetrievalType:  proto.RetrievalType_RT_SEARCH,
		Goal:           searchArgs.Goal,
		Extract:        searchArgs.Extract,
		Queries:        searchArgs.Queries,
		SourcesName:    searchArgs.Sources,
		LastRoundItems: lastRoundItems,
	})

	recallItems, err := d.deepSearchRecallService.Recall(ctx, requestCtx)

	if err != nil {
		return resList, err
	}

	return recallItemToResultItemList(requestCtx, recallItems), nil
}

// handleBrowseTool 处理浏览工具
func (d *DeepSearchLogic) handleBrowseTool(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	lastRoundItems []*data_frame.ItemData[entities.Item], browseArgs *BrowseToolArgs) ([]*data_frame.ItemData[entities.Item], error) {
	log.Infof(ctx, "Executing search tool...")

	resList := make([]*data_frame.ItemData[entities.Item], 0)

	requestCtx.GetBizContext().SetDeepSearchContext(&entities.DeepSearchContext{
		RetrievalType:  proto.RetrievalType_RT_BROWSE,
		Goal:           browseArgs.Goal,
		Extract:        browseArgs.Extract,
		Priority:       entities.PriorityType(browseArgs.Priority),
		SourcesName:    []string{browseArgs.Source},
		LastRoundItems: lastRoundItems,
	})

	recallItems, err := d.deepSearchRecallService.Recall(ctx, requestCtx)

	if err != nil {
		return resList, err
	}

	return recallItemToResultItemList(requestCtx, recallItems), nil
}

// handleSelectTool 处理选择工具
func (d *DeepSearchLogic) handleSelectTool(ctx context.Context, goals []string, references []*data_frame.ItemData[entities.Item], selectArgs *SelectToolArgs, modelTraces []*ModelTrace, retrievalProducer *chat_event.ChatEventByRetrievalProducer) ([]*data_frame.ItemData[entities.Item], string, error) {
	log.Infof(ctx, "Executing select tool...")

	var selectedReferences []*data_frame.ItemData[entities.Item]
	var renderedContent string

	// 记录最终 trace
	defer func() {
		retrievalProducer.Tracing(util.GetJSONIgnoreError(map[string]interface{}{
			"model":   modelTraces,
			"message": util.UnicodeSubstr(renderedContent, 0, 1024),
			"items": lo.Map(selectedReferences, func(item *data_frame.ItemData[entities.Item], _ int) string {
				return item.GetBizItem().ToDescription()
			}),
		}))
	}()

	// 过滤合法的ID
	var selectedIDs []int
	if selectArgs != nil {
		for _, id := range selectArgs.ContentIDs {
			if id >= 0 && id < len(references) {
				selectedIDs = append(selectedIDs, id)
			}
		}
	}

	// 如果没有选择任何内容，选择所有引用
	if len(selectedIDs) == 0 {
		for i := range references {
			selectedIDs = append(selectedIDs, i)
		}
	}

	// 随机补 reference 直到 token 打满
	omittedIDs := make([]int, 0)
	selectedIDMap := make(map[int]bool)
	for _, id := range selectedIDs {
		selectedIDMap[id] = true
	}
	for i := range references {
		if !selectedIDMap[i] {
			omittedIDs = append(omittedIDs, i)
		}
	}

	// 计算已选择的token数
	cumulate := 0
	for _, id := range selectedIDs {
		if id < len(references) {
			cumulate += references[id].GetBizItem().GetItemMeta().GetReadTokenLength()
		}
	}

	// 如果token数不足，随机添加更多references
	if cumulate < 65536 {
		// 随机打乱omittedIDs
		for i := len(omittedIDs) - 1; i > 0; i-- {
			j := rand.Intn(i + 1)
			omittedIDs[i], omittedIDs[j] = omittedIDs[j], omittedIDs[i]
		}

		for _, id := range omittedIDs {
			// 假设每个reference有selected_tokens字段
			after := cumulate + references[id].GetBizItem().GetItemMeta().GetReadTokenLength()
			if after > 65536 {
				continue
			}
			cumulate = after
			selectedIDs = append(selectedIDs, id)
		}
	}

	// 重新整理脚标序号，排序按照模型预测的重要性顺序
	for i, id := range selectedIDs {
		if id < len(references) {
			reference := references[id]
			// 重新设置index
			reference.GetBizItem().GetItemMeta().Index = i + 1
			// 设置chunk Text
			parasContents := make([]string, 0)
			for _, paras := range reference.GetBizItem().GetItemMeta().ReadParagraphs {
				for _, para := range paras {
					parasContents = append(parasContents, para.Content)
				}
			}
			reference.GetBizItem().Text = strings.Join(parasContents, "\n")
			// append
			selectedReferences = append(selectedReferences, reference)
		}
	}

	if len(selectedReferences) == 0 {
		return selectedReferences, renderedContent, nil
	}

	renderedContent, err := d.genFinalSummary(ctx, selectedReferences)

	if err != nil {
		log.Errorf(ctx, "Failed to render reference template: %v", err)
		return selectedReferences, renderedContent, err
	}

	return selectedReferences, renderedContent, nil
}

func (d *DeepSearchLogic) genFinalSummary(ctx context.Context, references []*data_frame.ItemData[entities.Item]) (string, error) {
	// 转换 selectedReferences 为模板需要的格式
	templateReferences := make([]map[string]interface{}, 0, len(references))
	for _, ref := range references {
		itemMeta := ref.GetBizItem().GetItemMeta()
		document := itemMeta.Document

		// 按顺序合并 itemMeta.ReadParagraphs 为 list
		var selection []int
		paragraphs := make(map[string]map[string]interface{})

		for _, paras := range itemMeta.ReadParagraphs {
			for _, para := range paras {
				selection = append(selection, para.ID)
				paraIDStr := fmt.Sprintf("%d", para.ID)
				paragraphs[paraIDStr] = map[string]interface{}{
					"content": para.Content,
					"id":      para.ID,
				}
			}
		}
		// 去重并排序
		selection = lo.Uniq(selection)
		sort.Ints(selection)

		// 构建模板需要的引用数据
		refData := map[string]interface{}{
			"Index":         itemMeta.Index,
			"Type":          model.GetDocTypeName(itemMeta.DocType),
			"Title":         itemMeta.Document.Title,
			"Author":        itemMeta.Document.AuthorName,
			"Sources":       document.Sources,
			"DatePublished": document.DatePublished,
			"DateAdded":     document.DateAdded,
			"Stats":         document.Stats,
			"Selection":     selection,
			"Paragraphs":    paragraphs,
		}

		templateReferences = append(templateReferences, refData)
	}

	// 构建模板数据
	templateData := map[string]interface{}{
		"references": templateReferences,
	}

	return d.promptService.BuildPromptWithApollo(ctx, "deepsearch_summary", "", "", 0, templateData)
}

// DigestInput 摘要输入结构
type DigestInput struct {
	Goal      string            `json:"goal"`
	Extract   string            `json:"extract"`
	Documents []*DigestDocument `json:"documents"`
}

// DigestDocument 摘要文档结构
type DigestDocument struct {
	Index         int                            `json:"index"`
	Title         string                         `json:"title"`
	AuthorName    string                         `json:"author_name"`
	Sources       string                         `json:"sources"`
	DatePublished string                         `json:"date_published"`
	DateAdded     string                         `json:"date_added"`
	URL           string                         `json:"url"`
	Stats         map[string]interface{}         `json:"stats"`
	Extraction    []int                          `json:"extraction"`
	Paragraphs    map[int]map[string]interface{} `json:"paragraphs"`
}

// DigestReference 摘要引用结构
type DigestReference struct {
	Type           string                 `json:"type"`
	Index          int                    `json:"index"`
	SelectedTokens int                    `json:"selected_tokens"`
	Title          string                 `json:"title"`
	AuthorName     string                 `json:"author_name"`
	Sources        string                 `json:"sources"`
	DateAdded      string                 `json:"date_added"`
	DatePublished  string                 `json:"date_published"`
	Stats          map[string]interface{} `json:"stats"`
}

func (d *DeepSearchLogic) digestTool(ctx context.Context, goal string, extract string, items []*data_frame.ItemData[entities.Item], digestProducer chat_event.EventProducer[*chat_event.AnswerContent]) string {
	if len(items) == 0 {
		if digestProducer != nil {
			digestProducer.Tracing("Items is empty")
		}
		return ""
	}

	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "research.digestTool",
		"logicName": d.GetName(),
	})

	// 构建文档列表
	documents := make([]*DigestDocument, 0, len(items))
	for i, item := range items {
		// 检查是否有提取的内容
		extractParagraphs := item.GetBizItem().GetItemMeta().ReadParagraphs[extract]
		if len(extractParagraphs) == 0 {
			continue
		}
		extraction := make([]int, 0, len(extractParagraphs))
		paragraphs := make(map[int]map[string]interface{})

		for _, para := range extractParagraphs {
			extraction = append(extraction, para.ID)
			paragraphs[para.ID] = map[string]interface{}{
				"content": para.Content,
				"id":      para.ID,
			}
		}

		doc := &DigestDocument{
			Index:         i,
			Title:         item.GetBizItem().GetItemMeta().Document.Title,
			AuthorName:    item.GetBizItem().GetItemMeta().Document.AuthorName,
			Sources:       item.GetBizItem().GetItemMeta().Document.Sources,
			DatePublished: item.GetBizItem().GetItemMeta().Document.DatePublished,
			DateAdded:     item.GetBizItem().GetItemMeta().Document.DateAdded,
			URL:           item.GetBizItem().GetItemMeta().Document.URL,
			Stats:         item.GetBizItem().GetItemMeta().Document.Stats,
			Extraction:    extraction,
			Paragraphs:    paragraphs,
		}
		documents = append(documents, doc)
	}

	// 如果没有有效的文档，返回空字符串
	if len(documents) == 0 {
		if digestProducer != nil {
			digestProducer.Tracing("Documents is empty")
		}
		return ""
	}

	// 构建输入结构
	digestInput := DigestInput{
		Goal:      goal,
		Extract:   extract,
		Documents: documents,
	}

	// 构建系统提示
	systemPrompt, err := d.promptService.BuildPromptWithApollo(ctx, "digest_system", "", "", 0, nil)
	if err != nil {
		errMsg := fmt.Sprintf("Failed to build digest system prompt: %v", err)
		log.Error(ctx, errMsg)
		if digestProducer != nil {
			digestProducer.Tracing(errMsg)
		}
	}

	// 构建用户提示
	log.Infof(ctx, "digestInput type: %T, Documents count: %d", digestInput, len(digestInput.Documents))
	userPrompt, err := d.promptService.BuildPromptWithApollo(ctx, "digest_user", "", "", 0, digestInput)
	if err != nil {
		errMsg := fmt.Sprintf("Failed to build digest user prompt: %v", err)
		log.Error(ctx, errMsg)
		if digestProducer != nil {
			digestProducer.Tracing(errMsg)
		}
		return ""
	}

	// 构建消息
	messages := []*dto.ChatRequestMessage{
		{
			Role:    dto.ChatRequestMessageRoleSystem,
			Content: systemPrompt,
		},
		{
			Role:    dto.ChatRequestMessageRoleUser,
			Content: userPrompt,
		},
	}

	chatReq := &dto.ChatRequest{
		ModelName:    "zhida-doubao-seed-1-6-flash",
		Messages:     messages,
		TopP:         lo.ToPtr[float32](0.5),
		ThinkingType: string(conf.ThinkingTypeDisabled),
	}

	// 记录 tracing
	if digestProducer != nil {
		digestProducer.Tracing(util.GetJSONIgnoreError(chatReq))
	}

	lastContent := ""
	resultStream := d.modelGatewayRPC.StreamChat(ctx, chatReq)
	for progress := range resultStream {
		if progress.E != nil {
			if errors.Is(progress.E, context.Canceled) {
				logger.Infof(ctx, "failed to chat with model gateway. err: %+v", progress.E)
			} else {
				logger.Errorf(ctx, "failed to chat with model gateway. err: %+v", progress.E)
			}
			break
		}
		lastContent = progress.V.Content
		if digestProducer != nil {
			// 推送数据到event
			digestProducer.Send(&chat_event.AnswerContent{
				Content: lastContent,
			})
		}
	}
	return lastContent
}

func (d *DeepSearchLogic) genDigestMessage(ctx context.Context, summary string, references []*data_frame.ItemData[entities.Item], candidates []*data_frame.ItemData[entities.Item]) string {
	// 构建摘要模板输入
	digestReferences := make([]*DigestReference, 0, len(candidates))

	// 创建 references 的索引映射，用于快速查找 candidate 在 references 中的位置
	referenceIndexMap := make(map[*data_frame.ItemData[entities.Item]]int)
	for i, ref := range references {
		referenceIndexMap[ref] = i
	}

	for _, candidate := range candidates {
		// 查找 candidate 在 references 中的索引
		refIndex, exists := referenceIndexMap[candidate]
		if !exists {
			log.Warnf(ctx, "Candidate not found in references, skipping")
			continue
		}

		ref := &DigestReference{
			Type:           model.GetDocTypeName(candidate.GetBizItem().GetItemMeta().DocType),
			Index:          refIndex,
			SelectedTokens: candidate.GetBizItem().GetItemMeta().Document.GetTokenLength(),
			Title:          candidate.GetBizItem().GetItemMeta().Document.Title,
			AuthorName:     candidate.GetBizItem().GetItemMeta().Document.AuthorName,
			Sources:        candidate.GetBizItem().GetItemMeta().Document.Sources,
			DateAdded:      candidate.GetBizItem().GetItemMeta().Document.DateAdded,
			DatePublished:  candidate.GetBizItem().GetItemMeta().Document.DatePublished,
			Stats:          candidate.GetBizItem().GetItemMeta().Document.Stats,
		}
		digestReferences = append(digestReferences, ref)
	}

	digestTemplateInput := map[string]interface{}{
		"References": digestReferences,
		"Digest":     summary,
	}

	// 构建摘要模板内容
	digestContent, err := d.promptService.BuildPromptWithApollo(ctx, "digest_message", "", "", 0, digestTemplateInput)
	if err != nil {
		log.Errorf(ctx, "Failed to build digest template: %v", err)
		digestContent = summary // 使用原始摘要作为降级
	}

	return digestContent
}

func (d *DeepSearchLogic) riskCheckGoalOrSummary(ctx context.Context, memberId int64, messageId string, goal string, summary string) bool {
	req := rpc.RiskCheckDeepSearchDto{
		MemberId:      memberId,
		QuestionId:    messageId,
		Goal:          goal,
		RecallSummary: summary,
	}

	resp, err := d.riskClient.RiskCheckDeepSearch(ctx, req)
	if err != nil {
		log.Errorf(ctx, "Risk check failed: %v", err)
		return false
	}

	util.Increment(ctx, basic_macro.CommonStatsPrefix+fmt.Sprintf(".deepsearch.security.%v.count", resp.Res == rpc.RiskCheckResPass))

	return resp.Res == rpc.RiskCheckResPass
}

func (d *DeepSearchLogic) riskCheckQueries(ctx context.Context, memberId int64, messageId string, queries []string) []string {
	group := safe_group.NewGroupWithTimeout(fmt.Sprintf("%s_%s", d.GetName(), "RiskCheckQueries"), 3000).SetLimit(10)

	var resultMap sync.Map
	var safeQueries []string

	for _, query := range queries {
		group.Go(func() error {
			req := rpc.RiskCheckDeepSearchDto{
				MemberId:      memberId,
				QuestionId:    messageId,
				SearchKeyWord: query,
			}

			resp, err := d.riskClient.RiskCheckDeepSearch(ctx, req)
			pass := err == nil && resp != nil && resp.Res == rpc.RiskCheckResPass

			resultMap.Store(query, pass)
			return nil
		})
	}

	// 等待所有并发调用完成
	if err := group.Wait(); err != nil {
		log.Errorf(ctx, "Risk check queries failed: %v", err)
		return []string{}
	}

	// 安全通过的queries
	resultMap.Range(func(key, value interface{}) bool {
		query, _ := key.(string)
		pass, _ := value.(bool)
		if pass {
			safeQueries = append(safeQueries, query)
		}
		return true
	})

	return safeQueries
}

func recallItemToResultItemList(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], recallItems []*entities.Item) []*data_frame.ItemData[entities.Item] {
	resList := make([]*data_frame.ItemData[entities.Item], 0)

	for _, item := range recallItems {
		if len(item.GetItemMeta().ReadParagraphs) > 0 {
			resList = append(resList, item.IntoFrameItem(requestCtx))
		}
	}

	return resList
}

func genTools(sourceMap map[string]*req_macro.SourceInfo) []dto.Tool {
	result := make([]dto.Tool, 0)

	// 包含 index，则塞入 index source name
	indexSourceNames := getIndexSourceNames(sourceMap)
	browseSourceNames := getBrowseSourceNames(sourceMap)

	if len(indexSourceNames) > 0 {
		searchTool := util.DeepCopyByJSONAndReturn(&baseSearchTool).(*dto.Tool)

		// 获取 sources.items 的引用
		if properties, ok := searchTool.Function.Parameters["properties"].(map[string]interface{}); ok {
			if sources, ok := properties["sources"].(map[string]interface{}); ok {
				if items, ok := sources["items"].(map[string]interface{}); ok {
					// 在 items 中添加 enum 字段
					items["enum"] = indexSourceNames
				}
			}
		}

		result = append(result, *searchTool)
	} else if len(browseSourceNames) > 0 {
		browseTool := util.DeepCopyByJSONAndReturn(&baseBrowseTool).(*dto.Tool)
		// 获取 sources 的引用
		if properties, ok := browseTool.Function.Parameters["properties"].(map[string]interface{}); ok {
			if sources, ok := properties["source"].(map[string]interface{}); ok {
				// 在 source 中添加 enum 字段
				sources["enum"] = browseSourceNames
			}
		}

		result = append(result, *browseTool)
	}

	result = append(result, baseSelectTool)

	return result
}

func getIndexSourceNames(sourceMap map[string]*req_macro.SourceInfo) []string {
	var result []string
	for sourceName, sourceInfo := range sourceMap {
		if sourceInfo.Type == req_macro.SourceTypeIndex {
			result = append(result, sourceName)
		}
	}
	return result
}

func getBrowseSourceNames(sourceMap map[string]*req_macro.SourceInfo) []string {
	var result []string
	for sourceName, sourceInfo := range sourceMap {
		if sourceInfo.Type == req_macro.SourceTypePortfolio || sourceInfo.Type == req_macro.SourceTypeKnowledgeBase || sourceInfo.Type == req_macro.SourceTypeSelected {
			result = append(result, sourceName)
		}
	}
	return result
}

// sourceMap清洗是因为挂载与订阅混杂，todo：@wangran 对接后端订阅接口，把这个下线掉
func genSourceMap(searchSourceMap map[string][]*req_macro.SourceInfo) map[string]*req_macro.SourceInfo {
	isIndex := false

	for _, sourceInfos := range searchSourceMap {
		for _, sourceInfo := range sourceInfos {
			if sourceInfo.Type == req_macro.SourceTypeIndex {
				isIndex = true
				break
			}
		}
	}

	sourceMap := make(map[string]*req_macro.SourceInfo)
	for sourceName, sourceInfos := range searchSourceMap {
		for _, sourceInfo := range sourceInfos {
			sourceInfo.TypeStr = req_macro.SourceTypeStr[sourceInfo.Type]
			if isIndex && sourceInfo.Type == req_macro.SourceTypeIndex {
				sourceMap[sourceName] = sourceInfo
			}
			if !isIndex {
				sourceMap[sourceName] = sourceInfo
			}
		}
	}
	return sourceMap
}

func isOnlyMountDocs(sourceMap map[string]*req_macro.SourceInfo) bool {
	for _, sourceInfo := range sourceMap {
		if sourceInfo.Type != req_macro.SourceTypeSelected {
			return false
		}
	}
	return true
}

func getMountDocSourceNames(sourceMap map[string]*req_macro.SourceInfo) []string {
	var result []string
	for sourceName, sourceInfo := range sourceMap {
		if sourceInfo.Type == req_macro.SourceTypeSelected {
			result = append(result, sourceName)
		}
	}
	return result
}
