package grpc

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/conf/digital_author_conf"
	digital_model "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	discover_model "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/dialog_session"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/halo"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc/grpc_util"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/samber/lo"
	"github.com/spf13/cast"
	"go.uber.org/atomic"
	"google.golang.org/grpc"
)

var RegisterAispChatServiceServer = func(registrar grpc.ServiceRegistrar) {
	proto.RegisterAispChatServiceServer(registrar, NewAispChatService())
}

type AispChatService struct {
	proto.UnimplementedAispChatServiceServer
	sessionService service.DialogSessionService
}

var _ proto.AispChatServiceServer = &AispChatService{}

var responseStatsFmt = macro.CommonStatsPrefix + ".%s.%s"
var responseStatsFmtOrigin = macro.OriginCommonStatsPrefix + ".%s.%s"
var responseStatsByBizFmt = macro.CommonStatsPrefix + ".%s.%s.%s"

const countStatsSuffix = ".count"

func NewAispChatService() *AispChatService {
	return &AispChatService{
		sessionService: service.NewDialogSessionService(),
	}
}

func (s *AispChatService) StreamChat(req *proto.ChatRequest, stream proto.AispChatService_StreamChatServer) error {
	ctx := stream.Context()

	logger := log.WithField(ctx, "StreamChat.Request", req)
	logger.Infof(ctx, "Start, RequestParams:%v", util.GetJSONIgnoreError(req))

	if req.GetInfo() == nil {
		log.Infof(ctx, "AispChatService.StreamChat request is blocked. request:%s", util.GetJSONIgnoreError(req))
		resp := &proto.ChatResponse{
			State:   proto.ChatState_CANCELED,
			Message: nil,
		}
		_ = stream.Send(resp)
		statsd.Increment(fmt.Sprintf(responseStatsFmtOrigin+countStatsSuffix, req.GetType().String(), "request", "blocked"))
		return nil
	}

	// 如果sessionId 为空 则需要创建一个新session
	if req.GetInfo().GetSessionId() == "" {
		sessionId, err := s.sessionService.CreateSession(ctx, &proto.CreateSessionRequest{
			MemberId: req.GetInfo().GetMemberId(),
			Type:     req.GetType(),
		})
		if err == nil {
			req.GetInfo().SessionId = cast.ToString(sessionId)
		} else {
			logger.WithError(ctx, err).Error(ctx, "create session failed")
		}
	}

	// 初始化graph上下文
	logger.Infof(ctx, "bizRequestContext")
	configMap, stageConfig := s.getConfigMap(req)
	var bizRequestContext *entities.RequestContext
	if stageConfig != nil {
		bizRequestContext = entities.NewRequestContextFromChatRequestAndStageConf(req, stageConfig)
	} else {
		bizRequestContext = entities.NewRequestContextFromChatRequest(req, configMap)
	}
	defer bizRequestContext.ABCommit() // 手动提交数据给布谷实验平台

	// 初始化 productContext
	var productContext entities.ProductContext
	switch req.GetType() {
	case
		proto.ChatType_DISCOVER_TAB,
		proto.ChatType_PC_DISCOVER_TAB,
		proto.ChatType_ZHIDA_TAB,
		proto.ChatType_ZHIDA_V2,
		proto.ChatType_ZHIDA_PRO_TAB,
		proto.ChatType_ZHIDA_AGENT,
		proto.ChatType_ZHIDA_MCP,
		proto.ChatType_ZPLUS_BRAND:
		productContext = discover_model.NewDiscoverTabContext(req)
	}
	bizRequestContext.SetProductContext(productContext)
	bizRequestContext.SetAbParamMap(s.getAbParamMap(req))
	// bizRequestContext.SetAbGivenValue(macro.ZlabSceneIdAiRecDomain, map[string]string{"ac_search_entity": "1"})

	//scenes := bizRequestContext.Scenes()
	haloSpan := halo.NewHalo(ctx, "AISP_AispChatService_StreamChat", req.GetType().String())
	haloFTSpan := halo.NewHalo(ctx, "AISP_AispChatService_StreamChat_FirstToken", req.GetType().String())
	clientSourceSpan := halo.NewHalo(ctx, "AISP_AispChatService_StreamChat_ClientSource",
		fmt.Sprintf("%s_%s", req.GetType().String(), bizRequestContext.GetClientSource().String()))
	trafficSourceSpan := halo.NewHalo(ctx, "AISP_AispChatService_StreamChat_TrafficSource",
		fmt.Sprintf("%s_%s", req.GetType().String(), bizRequestContext.GetTrafficSource().String()))
	nowTime := time.Now()

	waitFirstToken := atomic.NewBool(true)

	defer func() {
		haloSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		clientSourceSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		trafficSourceSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		s.statsChatRequest(ctx, bizRequestContext, req)
	}()

	logger.Infof(ctx, "graph.RunGraph Start")
	itemList, _, _, err := graph.RunGraphByCallback(ctx, bizRequestContext, nil, func(eventData *chat_event.EventInfo) {
		// 首Token bds 打点
		if waitFirstToken.Load() && (eventData.GetCurrEventType() == chat_event.ThinkEventType || eventData.GetCurrEventType() == chat_event.AnswerEventType) {
			text := ""
			if len(eventData.GetThinkContent()) > 0 {
				text = eventData.GetThinkContent()
			}
			if eventData.GetCurrEventType() == chat_event.AnswerEventType && eventData.GetAnswerContent() != nil {
				text = eventData.GetAnswerContent().Content
			}

			if text != "" &&
				text != generate.ThinkingMessage &&
				text != generate.GetDeepThinkingMessage() &&
				text != generate.GetRetryMessage() {
				haloFTSpan.EndWithContext(ctx, time.Since(nowTime), nil)
				waitFirstToken.Store(false)
			}
		}

		resp := bizRequestContext.GetChatEventResponseHandler().Transition(eventData, &chat_event.TransitionContext{
			IsHitCache: bizRequestContext.IsHitCache(),
		})
		err := stream.Send(resp)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "send stream failed resp: %+v", resp)
			return
		}

		// 抽样 10% 输出，减少日志量
		if grpc_util.SampleWithProbability(0.1) {
			logger.Infof(ctx, "message: %+v", eventData)
		}
	})
	// 异常情况
	if err != nil || len(itemList) == 0 {
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "graph failed")
		} else {
			log.Infof(ctx, "AispChatService.StreamChat itemList is empty")
		}
		resp := &proto.ChatResponse{
			State:        proto.ChatState_CANCELED,
			Message:      nil,
			ReqSessionId: req.GetInfo().GetSessionId(),
		}
		s.statsResponseWithAb(ctx, bizRequestContext, resp, false, nowTime)
		err = stream.Send(resp)
		return nil
	}
	logger.Infof(ctx, "graph.RunGraph Done")

	// =================================================================================================================

	allEventData := bizRequestContext.GetChatEvent().GetAllEventData()
	lastResp := bizRequestContext.GetChatEventResponseHandler().TransitionSource(allEventData, true, &chat_event.TransitionContext{
		IsHitCache: bizRequestContext.IsHitCache(),
	})
	// 如果命中了缓存
	if bizRequestContext.IsHitCache() {
		if lastResp.GetChatStage() != proto.ChatStage_STAGE_ANSWER {
			logger.Warnf(ctx, "send cache resp. (stage != answer) resp: %+v", lastResp)
			resp := &proto.ChatResponse{
				State:        proto.ChatState_CANCELED,
				Message:      nil,
				ReqSessionId: req.GetInfo().GetSessionId(),
			}
			err = stream.Send(resp)
		} else {
			logger.Infof(ctx, "send cache resp. resp: %+v", lastResp)
			s.statsResponseWithAb(ctx, bizRequestContext, lastResp, false, nowTime)
			err = stream.Send(lastResp)
		}
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "send cache stream failed resp: %+v", lastResp)
		}
		return nil
	}

	// 如果不是answer 直接返回 需要补状态出去
	if lastResp.GetChatStage() != proto.ChatStage_STAGE_ANSWER {
		lastResp.ChatStage = proto.ChatStage_STAGE_ANSWER
		lastResp.State = proto.ChatState_PROCESSING
		lastResp.ChatStageState = proto.ChatStageState_CSS_BEGIN
		lastResp.RespType = proto.ChatRespType_PLAIN_TEXT
		err = stream.Send(lastResp)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "send stream failed resp: %+v", lastResp)
		}
		lastResp.State = proto.ChatState_COMPLETED
		lastResp.ChatStageState = proto.ChatStageState_CSS_END
	}

	// 构建最终响应
	if res, isExist := lo.First[*entities.Item](itemList); isExist {
		// 安全检查
		answerRefusedBySecurity := !res.GetSecurity().IsSecurityAllPassed()
		if answerRefusedBySecurity {
			log.Infof(ctx, "security is not passed res: %s ", util.GetJSONIgnoreError(res))
		}

		// 填充内容
		lastResp.Think = res.Think
		lastResp.Message = res.ToChatMessage()
		if res.ChatRespType != proto.ChatRespType_UNKNOWN_RESP {
			lastResp.RespType = res.ChatRespType
		}

		logger.Infof(ctx, "========> send Last resp. resp: %s", util.GetJSONIgnoreError(lastResp))
		s.statsResponseWithAb(ctx, bizRequestContext, lastResp, answerRefusedBySecurity, nowTime)
		err = stream.Send(lastResp)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "send stream failed")
		}
		return nil
	} else {
		logger.WithError(ctx, err).Warnf(ctx, "send stream failed, itemList first item is empty!")
		err = stream.Send(lastResp)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "send stream failed")
		}
		return nil
	}
}

func (s *AispChatService) DigitalAuthorChat(request *proto.DigitalAuthorRequestInfo, stream proto.AispChatService_DigitalAuthorChatServer) error {
	ctx := stream.Context()
	logger := log.WithField(ctx, "request", request)

	nowTime := time.Now()
	productContext := digital_model.NewDigitalAuthorContext(request)
	bizRequestContext := entities.NewRequestContextForDigitalChat(request, productContext, digital_author_conf.LogicBizConfigMap)

	//scenes := bizRequestContext.Scenes()

	waitFirstToken := atomic.NewBool(true)

	//var lastResp *proto.ChatResponse
	chatEvent2Response := chat_event.NewChatEventResponse("", request.GetRespMessageId())
	itemList, _, _, err := graph.RunGraphByCallback(ctx, bizRequestContext, nil, func(eventData *chat_event.EventInfo) {
		resp := chatEvent2Response.Transition(eventData, &chat_event.TransitionContext{
			IsHitCache: bizRequestContext.IsHitCache(),
		})
		if waitFirstToken.Load() && resp.Message != nil &&
			resp.Message.Text != "" &&
			resp.Message.Text != generate.GetRetryMessage() {
			waitFirstToken.Store(false)
		}

		if waitFirstToken.Load() {
			resp.State = proto.ChatState_INITIALIZATION
		}

		//lastResp = resp
		err := stream.Send(resp)
		if err != nil {
			logger.WithError(ctx, err).Errorf(ctx, "send stream failed resp: %+v", resp)
			return
		}

		// 抽样 10% 输出，减少日志量
		if grpc_util.SampleWithProbability(0.1) {
			logger.Infof(ctx, "message: %+v", eventData)
		}
	})

	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "graph failed")
		resp := &proto.ChatResponse{
			State:   proto.ChatState_CANCELED,
			Message: nil,
		}
		s.statsResponseWithAb(ctx, bizRequestContext, resp, false, nowTime)
		err = stream.Send(resp)
		return err
	}
	if len(itemList) == 0 {
		return errors.New("empty response")
	}
	res := itemList[0]

	digitalAuthorContext := bizRequestContext.ProductContext().(*digital_model.DigitalAuthorContext)
	hitTask := digitalAuthorContext.HitTask()
	multiChatSummary := digitalAuthorContext.MultiChatSummary()

	resp := &proto.ChatResponse{
		State:    proto.ChatState_COMPLETED,
		Message:  res.ToChatMessage(),
		RespType: res.ChatRespType,
	}

	if hitTask.GetId() != 0 {
		resp.ExtraRespInfo = &proto.ExtraRespInfo{
			TaskId:  hitTask.GetId(),
			Summary: multiChatSummary,
		}
	}

	log.Infof(ctx, "request:%s \n response:%s", util.GetJSONIgnoreError(request), util.GetJSONIgnoreError(resp))
	s.statsResponseWithAb(ctx, bizRequestContext, resp, false, nowTime)

	err = stream.Send(resp)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "send stream failed")
	}
	return nil
}

func (s *AispChatService) SuggestQueries(ctx context.Context, req *proto.SuggestQueriesRequest) (*proto.SuggestQueriesResponse, error) {
	logger := log.WithField(ctx, "request", req)
	logger.Info(ctx, "suggest queries do request")

	// 获取当前图配置
	configMap := s.getQueriesConfigMap(req)
	bizRequestContext := entities.NewRequestContextFromSuggestQueriesRequest(req, configMap, false)
	haloSpan := halo.NewHalo(ctx, "AISP_AispChatService_SuggestQueries", req.GetType().String())
	clientSourceSpan := halo.NewHalo(ctx, "AISP_AispChatService_SuggestQueries_ClientSource",
		fmt.Sprintf("%s_%s", req.GetType().String(), bizRequestContext.GetClientSource().String()))
	trafficSourceSpan := halo.NewHalo(ctx, "AISP_AispChatService_SuggestQueries_TrafficSource",
		fmt.Sprintf("%s_%s", req.GetType().String(), bizRequestContext.GetTrafficSource().String()))
	nowTime := time.Now()
	defer func() {
		bizRequestContext.ABCommit() // 手动提交数据给布谷实验平台
		// 上报打点
		haloSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		clientSourceSpan.EndWithContext(ctx, time.Since(nowTime), nil)
		trafficSourceSpan.EndWithContext(ctx, time.Since(nowTime), nil)
	}()

	queries := make([]*proto.Query, 0)
	itemList, _, _, err := graph.RunGraph(ctx, bizRequestContext, nil)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "run graph failed => SuggestQueries")
		s.statsQueryResponseWithAb(ctx, bizRequestContext, queries, nowTime)
		return nil, err
	}
	for _, item := range itemList {
		queryPoint := &proto.Query{
			Id:        item.QueryId,
			Query:     item.Text,
			QueryType: item.QueryType,
			RiskType:  strings.ToLower(item.QueryCensorType),
		}
		queries = append(queries, queryPoint)
	}

	s.statsQueryResponseWithAb(ctx, bizRequestContext, queries, nowTime)
	return &proto.SuggestQueriesResponse{
		Queries: queries,
	}, nil
}

func (s *AispChatService) BuildQuery(ctx context.Context, req *proto.BuildQueryRequest) (*proto.BuildQueryResponse, error) {
	logger := log.WithField(ctx, "request", req)
	logger.Info(ctx, "query merge do request")

	// 获取当前图配置
	graphLogicConfig, _ := conf.GetGraphConfig(conf.LogicConfigNameByQueryMerge)

	bizRequestContext := entities.NewRequestContextFromBuildQueryRequest(req, graphLogicConfig.GetBizConfigMap())
	itemList, _, _, err := graph.RunGraph(ctx, bizRequestContext, nil)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "run graph failed => BuildQuery")
		return nil, err
	}

	if itemList == nil || len(itemList) == 0 {
		logger.Warnf(ctx, "query merge is nil => %v", req)
		return &proto.BuildQueryResponse{}, nil
	}

	res := itemList[0]

	// 组装 Response消息
	response := proto.BuildQueryResponse{
		Query: &proto.Query{
			Query: res.Text,
		},
	}
	return &response, nil
}

func (s *AispChatService) CreateSession(ctx context.Context, req *proto.CreateSessionRequest) (*proto.CreateSessionResponse, error) {
	logger := log.WithField(ctx, "request", req)
	logger.Info(ctx, "create session do request")

	sessionId, err := s.sessionService.CreateSession(ctx, req)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "create session failed")
		return nil, err
	}

	// 返回SessionId
	return &proto.CreateSessionResponse{
		SessionId: sessionId,
	}, nil
}

// ===============================================================

func (s *AispChatService) getConfigMap(request *proto.ChatRequest) (map[string]map[string]string, stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item]) {
	//  优先匹配新版 获取当前图配置
	graphStageLogicConfig, isExistStageConfig := stage_handler.GetGraphStageConfig(stage_handler.BuildGraphLogicConfigName(graph_constant.ApiStreamChat, request.GetType().String()))
	if !isExistStageConfig {
		// 获取当前图配置
		graphLogicConfig, isExist := conf.GetGraphConfig(conf.BuildLogicConfigName(graph_constant.ApiStreamChat, request.GetType().String()))
		if !isExist {
			return map[string]map[string]string{}, nil
		}
		return graphLogicConfig.GetBizConfigMap(), nil
	}
	return graphStageLogicConfig.GetDefaultBizConfigMap(), graphStageLogicConfig
}

func (s *AispChatService) getQueriesConfigMap(request *proto.SuggestQueriesRequest) map[string]map[string]string {
	// 获取当前图配置
	graphLogicConfig, isExist := conf.GetGraphConfig(conf.BuildLogicConfigName(graph_constant.ApiSuggestQueries, request.GetType().String()))
	if !isExist {
		return map[string]map[string]string{}
	}
	return graphLogicConfig.GetBizConfigMap()
}

func (s *AispChatService) statsChatRequest(ctx context.Context, bizContext *entities.RequestContext, req *proto.ChatRequest) {
	// 修改标题&重新生成&模型 使用次数打点监控
	statsd.Increment(fmt.Sprintf(responseStatsFmtOrigin+countStatsSuffix, bizContext.Scenes(), "chat_schema", bizContext.GetChatSchema().String()))
	statsd.Increment(fmt.Sprintf(responseStatsFmtOrigin+countStatsSuffix, bizContext.Scenes(), "chat_style", req.GetChatStyle().String()))
	statsd.Increment(fmt.Sprintf(responseStatsFmtOrigin+countStatsSuffix, bizContext.Scenes(), "chat_model", req.GetChatModel().String()))
}

func (s *AispChatService) statsResponseWithAb(ctx context.Context, bizContext *entities.RequestContext, response *proto.ChatResponse, answerRefusedBySecurity bool, nowTime time.Time) {
	ctx = s.contextWithReq(ctx, bizContext)
	// 记录耗时
	util.Timing(ctx, responseStatsByBizFmt, time.Since(nowTime), "api", bizContext.GetBizType(), "request_time")
	// 记录请求数
	util.Increment(ctx, responseStatsByBizFmt, "api", bizContext.GetBizType(), "count")

	// 新
	// 打点空结果率
	util.Increment(ctx, responseStatsFmt+countStatsSuffix, "message", getAnswerStatsStr(ctx, len(response.GetMessage().GetText()) == 0, answerRefusedBySecurity))
	util.Increment(ctx, responseStatsFmt+countStatsSuffix, "relevant_query", getStatsEmptyStr(ctx, len(response.GetRelevantQueries()) == 0))
	util.Increment(ctx, responseStatsFmt+countStatsSuffix, "card", getStatsEmptyStr(ctx, len(response.GetCards()) == 0))
	// 打点结果长度
	util.TimingInMilSec(ctx, responseStatsFmt, float64(utf8.RuneCountInString(response.GetMessage().GetText())), "message", "length")
	util.TimingInMilSec(ctx, responseStatsFmt, float64(len(response.GetRelevantQueries())), "relevant_query", "length")
	util.TimingInMilSec(ctx, responseStatsFmt, float64(len(response.GetCards())), "card", "length")

	// 老 todo: 1天后下掉
	// 打点空结果率
	statsd.Increment(fmt.Sprintf(responseStatsFmtOrigin+countStatsSuffix, bizContext.Scenes(), "message", getAnswerStatsStr(ctx, len(response.GetMessage().GetText()) == 0, answerRefusedBySecurity)))
	statsd.Increment(fmt.Sprintf(responseStatsFmtOrigin+countStatsSuffix, bizContext.Scenes(), "relevant_query", getStatsEmptyStr(ctx, len(response.GetRelevantQueries()) == 0)))
	statsd.Increment(fmt.Sprintf(responseStatsFmtOrigin+countStatsSuffix, bizContext.Scenes(), "card", getStatsEmptyStr(ctx, len(response.GetCards()) == 0)))
	// 打点结果长度
	statsd.TimeInMilliseconds(fmt.Sprintf(responseStatsFmtOrigin, bizContext.Scenes(), "message", "length"), float64(utf8.RuneCountInString(response.GetMessage().GetText())))
	statsd.TimeInMilliseconds(fmt.Sprintf(responseStatsFmtOrigin, bizContext.Scenes(), "relevant_query", "length"), float64(len(response.GetRelevantQueries())))
	statsd.TimeInMilliseconds(fmt.Sprintf(responseStatsFmtOrigin, bizContext.Scenes(), "card", "length"), float64(len(response.GetCards())))

}

func (s *AispChatService) statsQueryResponseWithAb(ctx context.Context, bizContext *entities.RequestContext, queries []*proto.Query, nowTime time.Time) {
	ctx = s.contextWithReq(ctx, bizContext)
	// 记录耗时
	util.Timing(ctx, responseStatsByBizFmt, time.Since(nowTime), "api", bizContext.GetSuggestQueriesType().String(), "request_time")
	// 记录请求数
	util.Increment(ctx, responseStatsByBizFmt, "api", bizContext.GetSuggestQueriesType().String(), "count")
	util.TimingInMilSec(ctx, responseStatsByBizFmt, float64(len(queries)), "api_resp", "query", "length")
	// 老
	statsd.Increment(fmt.Sprintf(responseStatsFmtOrigin, bizContext.Scenes(), "query", getStatsEmptyStr(ctx, len(queries) == 0)))
	statsd.TimeInMilliseconds(fmt.Sprintf(responseStatsFmtOrigin, bizContext.Scenes(), "query", "length"), float64(len(queries)))
}

func (s *AispChatService) contextWithReq(ctx context.Context, bizContext *entities.RequestContext) context.Context {
	ctx = log.ContextWithScene(ctx, bizContext.Scenes())
	ctx = log.ContextWithMemberID(ctx, bizContext.MemberId())
	ctx = log.ContextWithAB(ctx, bizContext.GetAbParamValueStrSlice())
	ctx = log.ContextWithClientSource(ctx, bizContext.RequestHeader().GetClientSource())
	ctx = log.ContextWithTrafficSource(ctx, bizContext.RequestHeader().GetTrafficSource())
	ctx = log.ContextWithTrafficReference(ctx, bizContext.RequestHeader().GetTrafficReference())
	return ctx
}

func (s *AispChatService) getAbParamMap(request *proto.ChatRequest) map[zlab.SceneId][]zlab.ZlabValue {
	//  优先匹配新版 获取当前图配置
	graphStageLogicConfig, isExistStageConfig := stage_handler.GetGraphStageConfig(stage_handler.BuildGraphLogicConfigName(graph_constant.ApiStreamChat, request.GetType().String()))
	if !isExistStageConfig {
		// 获取当前图配置
		graphLogicConfig, isExist := conf.GetGraphConfig(conf.BuildLogicConfigName(graph_constant.ApiStreamChat, request.GetType().String()))
		if !isExist {
			return map[zlab.SceneId][]zlab.ZlabValue{}
		}
		return graphLogicConfig.GetAbParamMap()
	}
	return graphStageLogicConfig.GetAbParamMap()
}

func getStatsEmptyStr(ctx context.Context, isEmpty bool) string {
	if context.Canceled == ctx.Err() {
		return "canceled"
	} else if isEmpty {
		return "empty"
	} else {
		return "not_empty"
	}
}

func getAnswerStatsStr(ctx context.Context, isEmpty bool, answerRefusedBySecurity bool) string {
	if context.Canceled == ctx.Err() {
		return "canceled"
	} else if answerRefusedBySecurity {
		return "security_refused"
	} else if isEmpty {
		return "empty"
	} else {
		return "not_empty"
	}
}
