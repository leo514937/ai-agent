package meta_fetcher

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	baselog "git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/box/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-bidding_xg_tools/brandai"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/klara_model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
)

// @logicOutput: 0 | 意图 string
type QueryRouterLogic struct {
	*logic.FetcherLogicDecorator[entities.RequestContext, entities.User, entities.Item, macro.IntentionType]
	modelGatewayRPC    modelapi.ModelTarget
	klaraService       klara_model.KlaraModelService
	promptService      prompt.PromptMapperService
	postProcessFuncMap map[string]func(context.Context, *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], string) macro.IntentionType
}

func NewQueryRouterLogic(name string, config map[string]string) *QueryRouterLogic {
	res := &QueryRouterLogic{
		FetcherLogicDecorator: logic.NewFetcherLogicDecorator[entities.RequestContext, entities.User, entities.Item, macro.IntentionType](name, config),
		modelGatewayRPC:       rpc.DefaultModelGatewayRouter,
	}

	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.promptService = prompt.DefaultPromptMapperService
	res.initPostProcessFuncMap()

	return res
}

func (l *QueryRouterLogic) initPostProcessFuncMap() {
	l.postProcessFuncMap = make(map[string]func(context.Context, *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], string) macro.IntentionType)
	l.postProcessFuncMap["ad-brand-qa"] = func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], content string) macro.IntentionType {
		intentions := strings.Split(content, ":")
		if len(intentions) == 2 {
			externalInfo := &brandai.ExtraInfo{
				PriceRange: strings.TrimSpace(intentions[1]),
			}
			requestCtx.GetBizContext().SetBrandExternalInfo(externalInfo)
		}
		return macro.IntentionType(intentions[0])
	}
}

func (l *QueryRouterLogic) getRouteConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.RouteConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if configStr == "" {
		log.Errorf(ctx, "QueryRouterLogic getRouteConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), l.GetName()))
		return conf.RouteConfig{}
	}

	routeConfig := conf.RouteConfig{}
	err := json.Unmarshal([]byte(configStr), &routeConfig)
	if err != nil {
		log.Errorf(ctx, "QueryRouterLogic getRouteConfig error => config unmarshal error, config: %s, err: %v", configStr, err)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), l.GetName()))
		return conf.RouteConfig{}
	}

	if routeConfig.ModelName == "" {
		routeConfig.ModelName = entities.QueryRouterAIZhidaOnline
	}

	//ratio, err := util.String2Float64(config.GetString(macro.QueryRouterSwitchConfigName, "0.01"))
	//if err == nil && util2.RandFloat64() < ratio {
	//	routeConfig.ModelName = entities.QueryRouterOrigin
	//}
	return routeConfig
}

func (l *QueryRouterLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]macro.IntentionType, error) {
	resMap := make(map[data_frame.UniqueId]macro.IntentionType)

	span, ctx, logCtx, _ := logic_context.InitLogicContext(ctx, requestCtx, l.GetName(), "meta_fetcher.QueryRouterLogic.fetch")
	defer logic_context.DeferContext(span, l.GetName(), requestCtx, &resMap)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))
	// 初始化QueryRouter
	requestCtx.GetBizContext().GetChatEvent().GetRouterProducer()

	routeConfig := l.getRouteConfig(ctx, requestCtx)

	if !routeConfig.IsEnable {
		// items 为 queryMerge 的结果，长度为 1
		for _, item := range items {
			resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = macro.GetQueryRouteEmpty()
		}

		span.LogFields(log.Message("QueryRouterLogic.fetch disabled."))

		return resMap, nil
	}

	var intentionType macro.IntentionType

	query := requestCtx.GetBizContext().RequestMessage().GetText()
	if query == "" {
		intentionType = routeConfig.DefaultChoice
	} else {
		messages := l.mergeHistoryAndQuery(ctx, requestCtx, user, query, routeConfig)

		timeout := 1 * time.Second
		if routeConfig.Timeout > 0 {
			timeout = routeConfig.Timeout
		}
		newCtx, cancel := context.WithTimeout(ctx, timeout)
		defer cancel()
		routeResp, err := l.route(newCtx, requestCtx, logCtx, user, query, messages)
		if err != nil {
			log.Warnf(ctx, "QueryRouterLogic fetch error => route error, query: %s, err: %v", query, err)
			routeResp = routeConfig.DefaultChoice
		}
		intentionType = routeResp
	}

	// items 为 queryMerge 的结果，长度为 1
	for _, item := range items {
		resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = intentionType

		requestCtx.DataMap().SetString(logCtx, l.GetOutputName(0), intentionType.String())
	}

	statsd.Increment(fmt.Sprintf("aisp-core.scene.%s.intention.%s", log.GetSceneFromContext(ctx), intentionType.Name()))

	span.LogFields(log.Message("QueryRouterLogic.fetch done."))

	return resMap, nil
}

func (l *QueryRouterLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res macro.IntentionType) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.QueryRouterLogic.itemMerge")
	defer span.Finish()

	log.Infof(ctx, "QueryRouterLogic itemMerge => item: %s, res: %s", item.GetBizItem().Text, res)

	if res != macro.GetQueryRouteEmpty() {
		item.GetBizItem().GetItemMeta().IntentionType = res
	}

	return nil
}

func (l *QueryRouterLogic) route(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], logCtx context.Context, user *data_frame.UserData[entities.User],
	query string, messages []*dto.ChatRequestMessage) (macro.IntentionType, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "route",
	})

	startTime := time.Now().UnixMilli()

	routeConfig := l.getRouteConfig(ctx, requestCtx)

	var responseFormat *dto.ChatCompletionsResponseFormat
	if routeConfig.ResponseFormat != nil {
		responseFormat = &dto.ChatCompletionsResponseFormat{
			RespType: routeConfig.ResponseFormat,
		}
	}

	aiProfile, err := l.buildPrompt(ctx, requestCtx, user, query, routeConfig.SystemPromptKey, routeConfig.SystemPrompt)
	if err != nil {
		logger.Errorf(ctx, "failed to build prompt. err: %+v", err)
		return routeConfig.DefaultChoice, err
	}

	req := &dto.ChatRequest{
		ModelName:      routeConfig.ModelName,
		AIProfile:      aiProfile,
		Messages:       messages,
		MaxTokens:      routeConfig.MaxTokens,
		Temperature:    routeConfig.Temperature,
		ResponseFormat: responseFormat,
		GuidedJson:     routeConfig.GuidedJson,
		GuidedChoice: lo.Map(routeConfig.GuidedChoice, func(s macro.IntentionType, _ int) string {
			return string(s)
		}),
	}

	if log.GetLevel() == baselog.DebugLevel {
		logger.Debugf(ctx, "llm query route messages:%v", util.GetJSONIgnoreError(req))
	}

	response, err := l.modelGatewayRPC.Chat(ctx, req)
	if err != nil {
		logger.Errorf(ctx, "failed to chat with model gateway. err: %+v", err)
		return routeConfig.DefaultChoice, err
	}

	content := response.Content
	// 删除首位空格和换行符
	content = strings.TrimSpace(content)
	// logger.Errorf(ctx, "query router result :%v", content)
	for _, choice := range routeConfig.GuidedChoice {
		if string(choice) == content {
			l.saveTracing(logCtx, req, content, startTime, requestCtx)
			return macro.IntentionType(content), nil
		}
	}
	if postFunc, exist := l.postProcessFuncMap[routeConfig.RouteBiz]; exist {
		return postFunc(ctx, requestCtx, content), nil
	}

	l.saveTracing(logCtx, req, content, startTime, requestCtx)

	return routeConfig.DefaultChoice, errors.New("not found guided choice in response")
}

func (l *QueryRouterLogic) saveTracing(logCtx context.Context, request *dto.ChatRequest, response string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   l.GetName(),
		LogicInput:  []string{util.GetJSONIgnoreError(request)},
		LogicOutput: []string{response},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(l.GetName(), logicTracing)
	requestCtx.GetBizContext().ProcessTracing().Intention = response

	llmRecord := &proto.LlmRecord{
		ModelName: request.ModelName,
		Messages:  model.ChatRequestMessages2Messages(request.AIProfile, request.Messages),
		Param:     model.ChatRequest2LlmParam(request),
		Response:  response,
	}
	requestCtx.GetBizContext().GetMiddleProcess().QueryRouter = llmRecord

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(request))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", response)

	// 发送QueryRouter结果
	requestCtx.GetBizContext().GetChatEvent().GetRouterProducer().Tracing(util.GetJSONIgnoreError(llmRecord)).Send(response).Done()
}

// handleHistoryDialogue 处理历史对话
func (l *QueryRouterLogic) mergeHistoryAndQuery(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], query string, routeConfig conf.RouteConfig) []*dto.ChatRequestMessage {
	messages := make([]*dto.ChatRequestMessage, 0)
	if routeConfig.IsNeedHistory {
		messages = append(messages, message.HistToChatRequestMessage(requestCtx.GetBizContext().GetHistoryDialogue())...)

		// 过滤对话历史 保持不超过 chatHistoryRound 长度
		if len(messages) > 0 {
			// 反转对话历史 保留里用户最近的历史内容
			reverseMessages := lo.Reverse(messages)
			dialogs := reverseMessages[:zrecUtil.Min(routeConfig.ChatHistoryRoundLimit, len(reverseMessages))]
			messages = lo.Reverse(dialogs)
		}
	}

	content, err := l.buildPrompt(ctx, requestCtx, user, query, routeConfig.QueryPromptKey, routeConfig.QueryPrompt)
	if err != nil {
		log.Warnf(ctx, "failed to build prompt. err: %+v", err)

		messages = append(messages, &dto.ChatRequestMessage{
			Content: content,
			Role:    dto.ChatRequestMessageRoleUser,
		})

		return messages
	}

	messages = append(messages, &dto.ChatRequestMessage{
		Content: content,
		Role:    dto.ChatRequestMessageRoleUser,
	})
	return messages
}

func (l *QueryRouterLogic) buildPrompt(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], query string, promptKey string, defaultPrompt string) (string, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "buildPrompt",
	})

	promptInput := model.PromptInput{
		Query: query,
	}

	if userMeta := requestCtx.GetBizContext().AuthorInfo().UserMeta(); userMeta != nil {
		promptInput.Topic = userMeta.GetFinalSkilledAnswer()
		promptInput.AuthorName = userMeta.GetUserName()
	}

	memberID := user.GetBizUser().MemberId
	promptTemp := l.promptService.LoadPromptByApollo(ctx, promptKey, defaultPrompt, "", memberID)

	promptContent, err := model.GenPrompt(&promptInput, promptTemp, promptKey)
	if err != nil {
		log.Errorf(ctx, "QueryRouterLogic buildPrompt template parse error: %+v", err)
		return query, nil
	}

	logger.Infof(ctx, "prompt:%s", promptContent)

	return promptContent, nil
}
