package graph

import (
	"context"
	"fmt"
	"strings"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	ai_daily_graph "git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph"
	graph2 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph"
	graph4 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/api"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	zagMap "git.in.zhihu.com/zrec/zag-driver/pkg/core/driver"
	zagDriverEntities "git.in.zhihu.com/zrec/zag-driver/pkg/core/driver/entities"
	"git.in.zhihu.com/zrec/zag-driver/pkg/framework/constant"
	"git.in.zhihu.com/zrec/zag-driver/pkg/framework/tools"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame/consts"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	strategyEntities "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

var zagDriver *zagMap.ZagDriverImpl[data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]]

var graphMap = make(map[string]*graph.Graph)

func InitZagDriver(sceneName string) {
	log.Infof(context.Background(), "InitZagDriver start. sceneName: %s", sceneName)

	//声明模型 >>>逻辑图
	var graphList []*graph.Graph
	if sceneName == graph_constant.ApiDigitalAuthorChat {
		graphList = append(graphList, graph2.DigitalAuthorGraph[entities.RequestContext, entities.User, entities.Item]())
	} else if sceneName == graph_constant.ApiStreamChat {
		// 直答AI
		graphList = append(graphList, api.StreamChatDiscoverTabGraph[entities.RequestContext, entities.User, entities.Item](proto.ChatType_DISCOVER_TAB.String()))
		graphList = append(graphList, api.StreamChatDiscoverTabGraph[entities.RequestContext, entities.User, entities.Item](proto.ChatType_ZHIDA_TAB.String()))
		graphList = append(graphList, api.StreamChatDiscoverTabGraph[entities.RequestContext, entities.User, entities.Item](proto.ChatType_ZPLUS_BRAND.String()))
		// 直答专业版
		graphList = append(graphList, api.StreamChatZhidaProGraph[entities.RequestContext, entities.User, entities.Item]())
		// 直答 V2
		graphList = append(graphList, api.StreamChatZhiDaV2Graph[entities.RequestContext, entities.User, entities.Item](proto.ChatType_ZHIDA_V2.String()))
		// 直答 Agent
		graphList = append(graphList, api.StreamChatZhiDaAgentGraph[entities.RequestContext, entities.User, entities.Item]())
		// 直答 MCP
		graphList = append(graphList, api.ZhidaMCPGraph[entities.RequestContext, entities.User, entities.Item]())

		// 词相关
		graphList = append(graphList, api.QueriesAnswerAskGraph[entities.RequestContext, entities.User, entities.Item]())
		graphList = append(graphList, api.QueriesSpecifiedDocGraph[entities.RequestContext, entities.User, entities.Item]())
		graphList = append(graphList, api.QueriesGuidGraph[entities.RequestContext, entities.User, entities.Item](proto.SuggestQueriesType_DISCOVER_TAB_GUIDE.String()))
		graphList = append(graphList, api.QueriesGuidGraph[entities.RequestContext, entities.User, entities.Item](proto.SuggestQueriesType_ZHIDA_TAB_GUIDE.String()))
		graphList = append(graphList, api.QueryMergeGraph[entities.RequestContext, entities.User, entities.Item]())
	} else if sceneName == graph_constant.ApiZhihaituChat {
		graphList = append(graphList, graph4.ZhihaituApiGraph[entities.RequestContext, entities.User, entities.Item]())
		graphList = append(graphList, graph4.ZhihaituChatGraph[entities.RequestContext, entities.User, entities.Item]())
	} else if sceneName == graph_constant.ApiAIDailyPlaylist {
		graphList = append(graphList, ai_daily_graph.AIDailyPlaylistGraph[entities.RequestContext, entities.User, entities.Item]())
	}

	log.Infof(context.Background(), "driverConfig config. sceneName: %s", sceneName)

	//逻辑图 >>>物理图
	driverConfig := zagDriverEntities.NewDriverConfig() //物理图执行器配置
	driverConfig.SetMaxConcurrency(1000000)
	driverConfig.SetUsePool(false)
	driverConfig.SetDriverLogSwitch(false)
	driverConfig.SetOpenSamplingLog(true)
	driverConfig.SetSamplingRate(100)
	driverConfig.SetPlatformMetricSwitch(true)
	log.Infof(context.Background(), "GraphToZagDriverMultiple start. sceneName: %s", sceneName)
	for _, graphItem := range graphList {
		graphMap[graphItem.Name] = graphItem
		fmt.Printf("============================\n")
		fmt.Printf("======= graph: %+v \n", graphItem)
		fmt.Printf("============================\n")
	}

	zagDriver = zagHandler.GraphToZagDriverMultiple[entities.RequestContext, entities.User, entities.Item](graphList, driverConfig)
	log.Infof(context.Background(), "GraphToZagDriverMultiple end. sceneName: %s", sceneName)

	zagDriver.ToString(sceneName)
}

func RunGraph(ctx context.Context,
	bizRequestContext *entities.RequestContext,
	extraDataMap func(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error) ([]*entities.Item, interface{}, *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], error) {
	return RunGraphByCallback(ctx, bizRequestContext, extraDataMap, nil)
}

func RunGraphByCallback(ctx context.Context,
	bizRequestContext *entities.RequestContext,
	extraDataMap func(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error,
	streamingCallback func(eventData *chat_event.EventInfo)) ([]*entities.Item, interface{}, *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], error) {

	// 创建 Event
	timeout := int64(900 * 1000) // 总体耗时15分钟
	bizRequestContext.InitChatEvent(streamingCallback)
	group := safe_group.NewGroupWithTimeout("runGraphWait", timeout)
	group.Go(func() error {
		bizRequestContext.GetChatEvent().AWait()
		return nil
	})

	scenes := bizRequestContext.Scenes()
	memberID := bizRequestContext.MemberId()

	// 填充 ab 实验结果
	for sceneId, zlabParams := range bizRequestContext.GetAbParamMap() {
		for _, zlabParam := range zlabParams {
			abContext := bizRequestContext.GetABContext(sceneId)
			abValue := abContext.GetZlabABValue(zlabParam)
			bizRequestContext.AddAbParamValue(sceneId, zlabParam.Key, abValue)
		}
	}

	ctx = log.ContextWithScene(ctx, scenes)
	ctx = log.ContextWithMemberID(ctx, memberID)
	ctx = log.ContextWithAB(ctx, bizRequestContext.GetAbParamValueStrSlice())
	ctx = log.ContextWithClientSource(ctx, bizRequestContext.RequestHeader().GetClientSource())
	ctx = log.ContextWithTrafficSource(ctx, bizRequestContext.RequestHeader().GetTrafficSource())
	ctx = log.ContextWithTrafficReference(ctx, bizRequestContext.RequestHeader().GetTrafficReference())

	span, ctx, _ := log.StartChildSpanWithContext(ctx, "graph.RunGraph.func", log.Tags{
		"aisp_core.graph.scenes": scenes,
	})
	defer span.Finish()

	span.LogFields(log.Message(util.GetJSONIgnoreError(bizRequestContext)))

	logger := log.WithFields(ctx, map[string]interface{}{
		"func":   "RunGraph",
		"scenes": scenes,
	})

	statsd.Increment(fmt.Sprintf("aisp_core.graph.run.%s.init", scenes))

	var requestId string
	if ctx.Value(constant.TraceIdKey) != nil {
		requestId = ctx.Value(constant.TraceIdKey).(string)
	} else {
		requestId = tools.GetNextId()
	}
	// 初始化 zag framework 层自动添加的框架算子元信息
	requestContext := data_frame.NewRequestContext[entities.RequestContext, entities.User, entities.Item]()
	requestContext.GetCommonContext().SetServiceName(scenes)
	requestContext.GetCommonContext().SetRequestId(requestId)
	requestContext.GetCommonContext().SetLimit(1)
	requestContext.SetBizContext(bizRequestContext)

	// 跑 case 模式下，获取受影响算子
	if bizRequestContext.GetRunCaseConfig().IsOpen || bizRequestContext.GetRunCaseConfig().IsUseSessionCache {
		caseAffectedLogics := getCaseAffectedLogics(
			graphMap[scenes],
			bizRequestContext.GetRunCaseConfig().LogicConfig,
			bizRequestContext.GetRunCaseConfig().ManualDirectAffectedLogics)
		bizRequestContext.SetRunCaseAffectedLogics(caseAffectedLogics)
	}

	u := requestContext.GetCommonContext().GetLogicData(consts.User_key).(*data_frame.UserData[entities.User])
	bizUser := entities.NewUser(u)
	bizUser.SetMemberId(bizRequestContext.MemberId())
	u.SetBizUser(bizUser)

	if extraDataMap != nil {
		err := extraDataMap(requestContext)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "set extraDataMap error")
			return nil, nil, nil, err
		}
	}

	logger.Infof(ctx, "Scenes %s", scenes)

	endNodeName := getEndNodeName(bizRequestContext.GetRunCaseConfig().IsOpen, scenes)

	// 超时时间 由原先5分钟改为10分钟（新需求中模型生成html耗时大概为5-10分钟，当zag-graph超时后会导致 tracing无法写入）
	config := strategyEntities.NewRuntimeConfig[entities.RequestContext, entities.User, entities.Item](endNodeName, bizRequestContext.Scenes(), timeout)
	config.AddNodeListener(endNodeName, func(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
		logger.Infof(ctx, "请求正常结束！requestContext.FlowResponse size: %d", len(requestContext.GetBizContext().ResponseItemList()))
	})
	finalEnd := make(chan bool, 1)
	if endNodeName != macro.EndNode {
		config.AddNodeListener(macro.EndNode, func(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
			logger.Infof(ctx, "graph节点全部结束！requestContext.")
			finalEnd <- true
		})
	}
	config.SetTimeoutFunc(func(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
		logger.Info(ctx, "zag timeout")
		if requestContext.GetBizContext().ResponseItemList() == nil {
			logger.Infof(ctx, "requestContext.FlowResponse nil")
		} else {
			logger.Infof(ctx, "requestContext.FlowResponse size: %d", len(requestContext.GetBizContext().ResponseItemList()))
		}
	})

	logger.Infof(ctx, "GraphRun Start.")
	statsd.Increment(fmt.Sprintf("aisp_core.graph.run.%s.start", scenes))
	err := zagHandler.GraphRun[entities.RequestContext, entities.User, entities.Item](ctx, requestContext, zagDriver, config)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "GraphRun error")
	}
	logger.Infof(ctx, "GraphRun Done.")
	bizRequestContext.GetChatEvent().ProducerDone()
	_ = group.Wait()

	statsd.Increment(fmt.Sprintf("aisp_core.graph.run.%s.done", scenes))
	itemList := requestContext.GetBizContext().ResponseItemList()

	// 约定响应结果都用这个key: graph_macro.ZagKeyResponse
	chatResponse, _ := requestContext.DataMap().GetObjMap(ctx, graph_macro.ZagKeyResponse)

	logger.Infof(ctx, "请求正常结束！requestContext.FlowResponse itemList: %+v", itemList)
	statsd.Increment(fmt.Sprintf("aisp_core.graph.run.%s.return", scenes))

	if bizRequestContext.GetIsTest() {
		requestContext.DataMap().SetObjMap(ctx, graph_macro.ZagKeyFinalEnd, finalEnd)
		return itemList, chatResponse, requestContext, nil
	} else {
		return itemList, chatResponse, nil, nil
	}
}

// 获取配置变更后受影响的算子
func getCaseAffectedLogics(graph *graph.Graph, LogicConfig map[string]map[string]string, manualDirectAffectedLogics []string) []string {
	var affectLogicNames []string
	if graph == nil {
		return affectLogicNames
	}

	logicNames := lo.Uniq(append(lo.Keys(LogicConfig), manualDirectAffectedLogics...))

	for _, logicName := range logicNames {
		// 填充 config 中出现的算子，该算子发生配置变更，直接受影响
		affectLogicNames = append(affectLogicNames, logicName)
		for idx, logic := range graph.GetLogics() {
			if logic.GetName() == logicName {
				// 填充算子的后继算子，间接受影响
				affectLogicNames = append(affectLogicNames, getPostLogicNames(logic, []string{})...)
				break
			}
			if idx == len(graph.GetLogics())-1 {
				panic(fmt.Sprintf("Can not find logic in graph:%s", logicName))
			}
		}
	}
	return lo.Uniq(affectLogicNames)

}

func getPostLogicNames(logic *graph.Logic, postLogicNames []string) []string {
	if len(logic.GetPostLogics()) == 0 {
		return postLogicNames
	}

	for _, postLogic := range logic.GetPostLogics() {
		postLogicNames = append(postLogicNames, postLogic.Name)
		postLogicNames = getPostLogicNames(postLogic, postLogicNames)
	}

	return postLogicNames
}

func getEndNodeName(isRunCase bool, sceneName string) string {
	if isRunCase {
		return macro.EndNode
	}

	// 优化EndNodeName（看逻辑是目前只有ChatType）
	for _, chatTypeName := range proto.ChatType_name {
		if strings.HasSuffix(sceneName, chatTypeName) {
			return macro.ResponseNode
		}
	}

	// 其他业务，在下方自行处理
	// ...

	return macro.EndNode
}
