package router

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/agent_tool"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	router_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router/sub_graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router/tools"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

type AgentRouterLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	retryMaxCount          int
	directChatSubService   sub_graph.IGraphService
	researchChatSubService sub_graph.IGraphService
	needToolTypes          []router_macro.RouterAgentToolType
	routerHistoryRound     int
}

func NewAgentRouterLogic(name string, config map[string]string) *AgentRouterLogic {
	res := &AgentRouterLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.routerHistoryRound = 3
	res.retryMaxCount = 2
	res.directChatSubService = sub_graph.NewDirectChatSubService()
	res.researchChatSubService = sub_graph.NewResearchChatSubService()
	res.MergeFunc = res.router
	res.needToolTypes = []router_macro.RouterAgentToolType{
		router_macro.RouterAgentByProfile,
		router_macro.RouterAgentByJailbreak,
		router_macro.RouterAgentByDirectReply,
		router_macro.RouterAgentByResearch,
	}
	return res
}

func (q *AgentRouterLogic) router(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	resp := make([]*data_frame.ItemData[entities.Item], 0)
	startTime := time.Now().UnixMilli()
	span, ctx, logCtx, _ := logic_context.InitLogicContext(ctx, requestCtx, q.GetName(), "AgentRouterLogic.router")
	defer logic_context.DeferContext(span, q.GetName(), requestCtx, &resp)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))
	logger := log.WithFields(ctx, map[string]any{
		"func": "AgentRouterLogic.router",
	})

	// 获取producer 默认发送Begin 事件
	routerProducer := requestCtx.GetBizContext().GetChatEvent().GetRouterProducer()

	// 创建Tools
	toolMap := q.getAgentToolMap(requestCtx)
	// 注册验证器
	toolCallValidator := agent_tool.NewToolCallValidator()
	for _, tool := range toolMap {
		toolCallValidator.RegisterTool(tool.GetName(), tool.GetParameters())
	}

	globalMessages := q.getMessages(requestCtx, q.getChatMsgConfig(ctx, requestCtx))
	// 设置当前message 到上下文中 供Research 和 StreamChat 使用
	requestCtx.GetBizContext().SetMessages(globalMessages)
	// 由模型选择工具
	chatRequest := q.getChatRequest(ctx, requestCtx, toolMap)

	// 最大尝试n次 调用tool, 默认为模型直接回答
	hitTool := dto.FunctionCallResult{
		Name:      router_macro.RouterAgentByDirectReply.String(),
		Arguments: "{\"thinking\", false}",
		ID:        "-1",
	}

	retryCount := 0
	if _, isExist := toolMap[router_macro.RouterAgentByResearch.String()]; isExist && len(toolMap) == 1 {
		hitTool = dto.FunctionCallResult{
			Name:      router_macro.RouterAgentByResearch.String(),
			Arguments: "",
			ID:        "-1",
		}
	} else {
		for range q.retryMaxCount {
			functionToolCall, valid := q.getRouterTool(ctx, chatRequest, toolCallValidator)
			if valid {
				if _, isExistTool := toolMap[functionToolCall.Name]; isExistTool {
					hitTool = functionToolCall
				}
				break
			}
			retryCount += 1
			logger.Warnf(ctx, "AgentRouterLogic.retryMaxCount[%d], currCount=%d", q.retryMaxCount, retryCount)
		}
	}

	// 记录Router Tracing
	routerProducer.Tracing(util.GetJSONIgnoreError(&AgentRouterTracing{ChatRequest: chatRequest, RetryCount: retryCount, HitToolName: hitTool.Name}))
	routerProducer.Send(hitTool.Name).Done()

	// 执行子图
	if _, isExistTool := toolMap[hitTool.Name]; isExistTool {
		itemList := make([]*entities.Item, 0)
		_ = safe_group.SafeRun(func() error {
			itemListTmp, err := toolMap[hitTool.Name].Run(ctx, hitTool)
			if err != nil {
				logger.Warnf(ctx, "agentRouter -> run-sub-graph Err: %s", err.Error())
				return err
			}

			if len(itemListTmp) > 0 {
				itemList = append(itemList, itemListTmp...)
			}
			return nil
		}, "agentRouter -> run-sub-graph")
		// 处理数据
		for _, item := range itemList {
			resp = append(resp, item.IntoFrameItem(requestCtx))
		}
	}

	// router 选择打点
	util.Increment(ctx, macro.CommonStatsPrefix+fmt.Sprintf(".agent_router.%s.count", hitTool.Name))
	q.saveTracing(logCtx, chatRequest, "", hitTool.Name, startTime, requestCtx)
	return resp, nil
}

func (q *AgentRouterLogic) getMessages(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], msgConf conf.MsgConfig) []*dto.ChatRequestMessage {
	// 拼装请求模型参数
	handlerConfigs := make([]conf.ChatMsgConfig, 0)
	handlerConfigs = append(handlerConfigs, conf.NewChatMsgConfigBySystem(msgConf.SystemPromptId, msgConf.SystemDefaultPromptTemplate, msgConf.SystemPromptTag))
	handlerConfigs = append(handlerConfigs, msgConf.MsgConfigArr...)
	messageHandler := generate.NewMessageHandler(handlerConfigs, requestCtx, make([]*data_frame.ItemData[entities.Item], 0), int64(54*1024), 0, 8192, true)
	return messageHandler.BuildAllMessages()
}

func (q *AgentRouterLogic) getChatRequest(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], toolMap map[string]agent_tool.IAgentTool) *dto.ChatRequest {
	modelName := requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.ConfigModelName)

	// 拼装请求模型参数
	routerMessages := q.getMessages(requestCtx, q.getRouterMsgConfig(ctx, requestCtx))

	// 构建 ChatRequest
	chatRequest := &dto.ChatRequest{
		ModelName: modelName,
		Messages:  routerMessages,
		Tools: lo.MapToSlice(toolMap, func(key string, value agent_tool.IAgentTool) dto.Tool {
			return value.ToFunction()
		}),
		ToolChoice: dto.ToolChoiceOptionsRequired,
		ExtraBody: map[string]interface{}{
			"thinking": map[string]string{"type": "disabled"},
		},
	}
	return chatRequest
}

func (q *AgentRouterLogic) getAgentToolMap(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) map[string]agent_tool.IAgentTool {
	result := make(map[string]agent_tool.IAgentTool)
	toolTypes := lo.Uniq(q.needToolTypes)

	// 额外判断
	informationSourceLength := len(requestCtx.GetBizContext().GetKnowledgeBases())
	mountNonTextLength := requestCtx.GetBizContext().GetCurrReferenceMount().GetMountNonTextLength()
	if mountNonTextLength > 0 && informationSourceLength == 0 {
		toolTypes = lo.Filter(toolTypes, func(item router_macro.RouterAgentToolType, index int) bool {
			return item == router_macro.RouterAgentByResearch
		})
	} else {
		if informationSourceLength == 0 {
			toolTypes = lo.Filter(toolTypes, func(item router_macro.RouterAgentToolType, index int) bool {
				return item != router_macro.RouterAgentByResearch
			})
		}
	}

	for _, toolType := range toolTypes {
		switch toolType {
		case router_macro.RouterAgentByProfile:
			tool := tools.NewProfileTool(requestCtx.GetBizContext(), q.directChatSubService)
			result[tool.GetName()] = tool
		case router_macro.RouterAgentByClarify:
			tool := tools.NewClarifyTool(requestCtx.GetBizContext(), q.directChatSubService)
			result[tool.GetName()] = tool
		case router_macro.RouterAgentByJailbreak:
			tool := tools.NewJailbreakTool(requestCtx.GetBizContext(), q.directChatSubService)
			result[tool.GetName()] = tool
		case router_macro.RouterAgentByDirectReply:
			tool := tools.NewDirectReplyTool(requestCtx.GetBizContext(), q.directChatSubService)
			result[tool.GetName()] = tool
		case router_macro.RouterAgentByResearch:
			tool := tools.NewResearchTool(requestCtx.GetBizContext(), q.researchChatSubService)
			result[tool.GetName()] = tool
		}
	}
	return result
}

func (q *AgentRouterLogic) getRouterTool(ctx context.Context,
	chatRequest *dto.ChatRequest,
	toolCallValidator *agent_tool.ToolCallValidator) (dto.FunctionCallResult, bool) {
	newCtx, cancel := context.WithTimeout(util.WithoutCancel(ctx), 5*time.Second)
	defer cancel()

	logger := log.WithFields(ctx, map[string]any{
		"func": "AgentRouterLogic.getRouterTool",
	})

	// 调用模型并校验
	modelGatewayRPC := rpc.DefaultModelGatewayRouter
	response, err := modelGatewayRPC.Chat(newCtx, chatRequest)
	//if err != nil || response == nil || !strings.HasPrefix(response.ResponseId, "resp_") {
	if err != nil || response == nil {
		logger.Warnf(newCtx, "ModelGatewayRPC.Responses failed: %v\n", err)
		return dto.FunctionCallResult{}, false
	}

	for _, functionCall := range response.FunctionCallResults {
		if functionCall.Name != "" {
			validateResult := toolCallValidator.ValidateToolCall(functionCall.Name, functionCall.Arguments)
			if validateResult.Valid {
				util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".tool_validate.agent_router.error_count", float64(0))
				return functionCall, true
			}
			util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".tool_validate.agent_router.error_count", float64(1))
		}
	}
	return dto.FunctionCallResult{}, false
}

func (q *AgentRouterLogic) getChatMsgConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.MsgConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.ChatMessageJsonConfig)
	if configStr == "" {
		log.Errorf(ctx, "AgentRouterLogic getChatMsgConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), q.GetName()))
		return conf.MsgConfig{}
	}

	chatMsgConfig := conf.MsgConfig{}
	err := json.Unmarshal([]byte(configStr), &chatMsgConfig)
	if err != nil {
		log.Errorf(ctx, "AgentRouterLogic getChatMsgConfig error => config is json unmarshal err")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), q.GetName()))
	}
	return chatMsgConfig
}

func (q *AgentRouterLogic) getRouterMsgConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.MsgConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.ChatMessageRouterJsonConfig)
	if configStr == "" {
		log.Errorf(ctx, "AgentRouterLogic getRouterMsgConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), q.GetName()))
		return conf.MsgConfig{}
	}

	chatMsgConfig := conf.MsgConfig{}
	err := json.Unmarshal([]byte(configStr), &chatMsgConfig)
	if err != nil {
		log.Errorf(ctx, "AgentRouterLogic getRouterMsgConfig error => config is json unmarshal err")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), q.GetName()))
	}
	return chatMsgConfig
}

func (q *AgentRouterLogic) saveTracing(logCtx context.Context, chatRequest *dto.ChatRequest, request string, response string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   q.GetName(),
		LogicInput:  []string{request},
		LogicOutput: []string{response},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(q.GetName(), logicTracing)

	if chatRequest != nil {
		llmRecord := &proto.LlmRecord{
			ModelName: chatRequest.ModelName,
			Messages:  model.ChatRequestMessages2MessagesBySource(chatRequest.Messages),
			Param:     model.ChatRequest2LlmParam(chatRequest),
			Response:  response,
		}
		requestCtx.GetBizContext().GetMiddleProcess().QueryRouter = llmRecord
	}

	constant.DataInputNodeLog.Infof(logCtx, "%v", request)
	constant.DataOutputNodeLog.Infof(logCtx, "%s", response)
}

type AgentRouterTracing struct {
	ChatRequest *dto.ChatRequest `json:"ChatRequest"`
	RetryCount  int              `json:"RetryCount"`
	HitToolName string           `json:"HitToolName"`
}
