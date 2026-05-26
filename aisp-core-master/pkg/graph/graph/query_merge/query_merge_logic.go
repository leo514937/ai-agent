package query_merge

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	baselog "git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/entities_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// QueryMergeLogic
// @logicAuthor: zhoupengcheng
// @logicInfo: query merge算子
// @logicConfig: 0 | 是否跳过并且把query merge 设置为query
type QueryMergeLogic struct {
	*logic.FilterLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	modelGatewayRPC modelapi.ModelTarget
}

func NewQueryMergeLogic(name string, config map[string]string) *QueryMergeLogic {
	res := &QueryMergeLogic{
		FilterLogicDecorator: logic.NewFilterLogicDecorator[entities.User, entities.Item](name, config),
	}

	res.modelGatewayRPC = rpc.DefaultModelGatewayRouter
	res.FilterFunc = res.realMapping
	return res
}

func (q *QueryMergeLogic) getChatConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.ChatConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if configStr == "" {
		log.Errorf(ctx, "QueryMergeLogic getChatConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), q.GetName()))
		return conf.ChatConfig{}
	}

	chatConfig := conf.ChatConfig{}
	err := json.Unmarshal([]byte(configStr), &chatConfig)
	if err != nil {
		log.Errorf(ctx, "QueryMergeLogic getChatConfig error => config unmarshal error, config: %s, err: %v", configStr, err)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), q.GetName()))
		return conf.ChatConfig{}
	}
	return chatConfig
}

func (q *QueryMergeLogic) getChatMsgConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.MsgConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.ChatMessageJsonConfig)
	if configStr == "" {
		log.Errorf(ctx, "QueryMergeLogic getChatMsgConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), q.GetName()))
		return conf.MsgConfig{}
	}

	chatMsgConfig := conf.MsgConfig{}
	err := json.Unmarshal([]byte(configStr), &chatMsgConfig)
	if err != nil {
		log.Errorf(ctx, "QueryMergeLogic getChatMsgConfig error => config is json unmarshal err")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), q.GetName()))
	}
	return chatMsgConfig
}

func (q *QueryMergeLogic) realMapping(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	resp := make([]*data_frame.ItemData[entities.Item], 0)

	logicContext := logic_context.InitLogicContextV2[[]*entities.Item](ctx, requestCtx, q.GetName(), "query_merge.QueryMergeLogic.realMapping")
	span := logicContext.Span
	ctx = logicContext.Ctx
	logCtx := logicContext.LogCtx
	defer func() {
		logicContext.DeferFunc(entities_util.DataFrameList2ItemList(&resp))
	}()
	// 如果有缓存 直接返回，直接返回
	if logicContext.CacheResp.IsOk && logicContext.CacheResp.Resp != nil && len(logicContext.CacheResp.Resp) > 0 {
		resp = q.genAndSetQueryMergeResultCustom(requestCtx, logicContext.CacheResp.Resp[0], logicContext.CacheResp.Resp[0].Text)
		return resp, nil
	}

	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	startTime := time.Now().UnixMilli()
	logger := log.WithFields(ctx, map[string]any{
		"func":          "QueryMergeLogic realMapping",
		"respMessageId": requestCtx.GetBizContext().RespMessageId(),
	})

	logger.Debug(ctx, "QueryMergeLogic realMapping 算子开始执行")
	if items == nil || len(items) == 0 {
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 用户原始query
	sourceQuery := requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent

	skipAndSetAsQuery := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.QueryMergeSkipAndSetAsQuery))
	if skipAndSetAsQuery {
		log.Infof(ctx, "logic execute skip: %s", q.GetName())
		// 设置query merge结果为query
		resp = q.genAndSetQueryMergeResult(requestCtx, sourceQuery)
		return resp, nil
	}

	// chat base 配置
	chatConfig := q.getChatConfig(ctx, requestCtx)
	// chat message 配置
	chatMsgConfig := q.getChatMsgConfig(ctx, requestCtx)

	aiProfile := chatConfig.AIProfile
	handlerConfigs := make([]conf.ChatMsgConfig, 0)
	handlerConfigs = append(handlerConfigs, conf.NewChatMsgConfigBySystem(chatMsgConfig.SystemPromptId, chatMsgConfig.SystemDefaultPromptTemplate, chatMsgConfig.SystemPromptTag))
	handlerConfigs = append(handlerConfigs, chatMsgConfig.MsgConfigArr...)
	messageHandler := generate.NewMessageHandler(handlerConfigs, requestCtx, items, int64(chatConfig.ContextLength), chatConfig.ExtraContextLength, *chatConfig.MaxTokens, false)
	// 处理数据
	// 1. 获取配置中的system信息，处理为system prompt
	systemPrompt, _, systemPromptErr := messageHandler.BuildPromptByDefPrompt(ctx,
		chatMsgConfig.SystemPromptId, chatMsgConfig.SystemDefaultPromptTemplate, chatMsgConfig.SystemPromptTag, "")
	if systemPromptErr == nil && systemPrompt != "" {
		aiProfile = systemPrompt
	}
	// 2. 将items 中清洗出召回内容 整理成知识库 并拼接为message
	messages := messageHandler.BuildMessages()

	req := &dto.ChatRequest{
		ModelName:         chatConfig.ModelName,
		AIProfile:         aiProfile,
		Messages:          messages,
		MaxTokens:         chatConfig.MaxTokens,
		Stop:              chatConfig.Stop,
		Temperature:       chatConfig.Temperature,
		TopP:              chatConfig.TopP,
		TopK:              chatConfig.TopK,
		RepetitionPenalty: chatConfig.RepetitionPenalty,
	}

	if log.GetLevel() == baselog.DebugLevel {
		logger.Debugf(ctx, "llm chat messages:%v", util.GetJSONIgnoreError(req))
	}

	// span.LogFields(log.Message("modelGatewayRPC.Chat start."),
	// 	log.Json("req", req),
	// )
	response, err := q.modelGatewayRPC.Chat(ctx, req)

	span.LogFields(log.Message("modelGatewayRPC.QueryMerge done."))

	var queryList []string
	if err == nil && response != nil {
		// response.Content 可能是一个 JSON 数组，也可能是单个字符串
		if err := json.Unmarshal([]byte(response.Content), &queryList); err != nil {
			// 先反序列化成字符串数组，如果失败，则按照单字符串处理
			queryList = []string{response.Content}
		}
	} else {
		logger.Errorf(ctx, "failed to chat with model gateway. err: %+v", err)
		queryList = []string{sourceQuery}
	}

	// 处理每个 query 并收集结果
	resp = make([]*data_frame.ItemData[entities.Item], 0)
	for idx, query := range queryList {
		queryMergeBeforeRes := query
		queryMergeRes := rebuildNewsQuery(queryMergeBeforeRes)
		// build QueryMerge 结果 如果失败的话 则query 兜底
		queryMergeRes = rebuildNewsQuery(lo.Ternary(queryMergeRes != "", queryMergeRes, query))

		// 为每个 query 生成结果
		itemResp := q.genAndSetQueryMergeResult(requestCtx, queryMergeRes)
		resp = append(resp, itemResp...)

		// 给端上发送关键词处理完成状态，只发送一次
		if idx == 0 && queryMergeRes != sourceQuery {
			requestCtx.GetBizContext().GetChatEvent().GetKeywordsProducer().Send([]string{queryMergeRes}).Done()
		}
	}

	// 记录 tracing，如果有多个 query，拼到一起
	queryMergeTracingStr := strings.Join(queryList, ",")
	requestCtx.GetBizContext().Tracing().ProcessTracing.QueryMerge = queryMergeTracingStr
	q.saveStatsd(ctx, chatConfig.ModelName, int(messageHandler.GetContextLength()), len(requestCtx.GetBizContext().GetHistoryDialogue()))
	q.saveTracing(logCtx, req, sourceQuery, queryMergeTracingStr, startTime, requestCtx)

	return resp, nil
}

func (q *QueryMergeLogic) saveTracing(logCtx context.Context, chatRequest *dto.ChatRequest, request string, response string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
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
			Messages:  model.ChatRequestMessages2Messages(chatRequest.AIProfile, chatRequest.Messages),
			Param:     model.ChatRequest2LlmParam(chatRequest),
			Response:  response,
		}
		requestCtx.GetBizContext().GetMiddleProcess().QueryMerge = llmRecord
	}

	constant.DataInputNodeLog.Infof(logCtx, "%v", request)
	constant.DataOutputNodeLog.Infof(logCtx, "%s", response)
}

// saveStatsd 保存打点信息
func (q *QueryMergeLogic) saveStatsd(ctx context.Context, op string, contentLen int, dialogCount int) {
	dialogCountStr := cast.ToString(dialogCount)
	if dialogCount >= 10 {
		dialogCountStr = "10p"
	}

	contentLenFmt := fmt.Sprintf("aisp-core.scene.%s.span.query_merge.%s.content_len",
		log.GetSceneFromContext(ctx), op)
	dialogCountFmt := fmt.Sprintf("aisp-core.scene.%s.span.query_merge.%s.dialog_count",
		log.GetSceneFromContext(ctx), op)
	dialogCountPartitionFmt := fmt.Sprintf("aisp-core.scene.%s.span.query_merge.%s.dialog_count_partition.%s",
		log.GetSceneFromContext(ctx), op, dialogCountStr)
	statsd.Timing(contentLenFmt, time.Duration(contentLen))
	statsd.Timing(dialogCountFmt, time.Duration(dialogCount))
	statsd.Increment(dialogCountPartitionFmt)
}

// 生成 query merge 的结果并存入 context.queryMerge
func (q *QueryMergeLogic) genAndSetQueryMergeResult(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], queryMergeRes string) []*data_frame.ItemData[entities.Item] {
	queryMergeItem := entities.ItemFromQueryMerge(&entities.Item{
		MessageId:   requestCtx.GetBizContext().RequestMessage().GetMessageId(),
		Type:        requestCtx.GetBizContext().RequestMessage().GetType(),
		TimestampMs: requestCtx.GetBizContext().RequestMessage().GetTimestampMs(),
	}, queryMergeRes)
	return q.genAndSetQueryMergeResultCustom(requestCtx, queryMergeItem, queryMergeRes)
}

// 生成 query merge 的结果并存入 context.queryMerge
func (q *QueryMergeLogic) genAndSetQueryMergeResultCustom(
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	item *entities.Item,
	queryMergeRes string) []*data_frame.ItemData[entities.Item] {
	queryMergeItem := entities.ItemFromQueryMerge(item, queryMergeRes)
	requestCtx.GetBizContext().SetQueryMerge(queryMergeItem)
	requestCtx.GetBizContext().AddQueryMergeList(queryMergeItem)
	return []*data_frame.ItemData[entities.Item]{
		queryMergeItem.IntoFrameItem(requestCtx),
	}
}

// 临时 trick: 针对新闻类 query 添加当前日期
func rebuildNewsQuery(query string) string {
	newsKeywords := []string{"新闻", "资讯", "热点", "热门", "热搜", "简讯", "热榜"}
	isNewsQuery := false

	for _, nk := range newsKeywords {
		if strings.Contains(query, nk) {
			isNewsQuery = true
			break
		}
	}

	curDate := util2.GetNowDate()

	dateKeywords := []string{"今天", "今日", "最近", "最新", "近期", "近日", "早间", "午间", "晚间"}
	if isNewsQuery {
		for _, dk := range dateKeywords {
			if strings.Contains(query, dk) {
				query = strings.Replace(query, dk, curDate+" ", 1)
				return query
			}
		}
	}

	return query
}
