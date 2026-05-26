package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/finalizer"
	prepare2 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/prepare"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_agent/graph/conf_stage"
	prepare3 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_agent/graph/logic/prepare"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_agent/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/logic/prepare"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/chat_cache"
	choose2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/choose"
	conf2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/consumer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// StreamChatZhiDaAgentGraph 直答 Agent
func StreamChatZhiDaAgentGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var apiConfigPath = zagHandler.GetApiConfigPath()
	var zagGraph = zagHandler.NewZagGraphDeclareWithInfo("chat_graph", entities.BuildGraphScene(graph_constant.ApiStreamChat, proto.ChatType_ZHIDA_AGENT.String()), "1.1", "zhoupengcheng,wangran", "直答Agent", apiConfigPath)

	//================流程声明================
	// 初始化阶段配置
	var initConfigStage = zagHandler.NewZagStageDeclare(conf.InitConfigStage)
	var initBeginConfig = zagHandler.NewZagLogicDeclare(conf.InitBeginConfigLogic).SetClass(empty.EmptyRootLogic{})
	var initConfig = zagHandler.NewZagLogicDeclare(conf.InitConfigLogic).SetClass(mapping.StageConfigLogic{}).AddPreLogic(initBeginConfig)
	initConfigStage.AddLogics(initBeginConfig, initConfig)

	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare(conf.RootStage).AddPres(initConfigStage)
	var copyUserMeta = zagHandler.NewZagLogicDeclare(conf.CopyUserMetaLogic).SetClass(root.CopyUserMetaLogic{})
	var userMessage = zagHandler.NewZagLogicDeclare(conf.UserMessageLogic).SetClass(root.UserMessageLogic{}).SetStore(conf2.SourceQueryItemLogicStoreKey.String()).
		AddPreLogic(copyUserMeta)
	stageRoot.AddLogics(copyUserMeta, userMessage)

	//------请求参数合法校验------
	var requestLegalityStage = zagHandler.NewZagStageDeclare(conf.RequestLegalityStage).AddPres(stageRoot)
	var requestLegalityChooseLogic = zagHandler.NewZagLogicDeclare(conf.RequestLegalityLogic).SetClass(choose2.RequestLegalityVerifyLogic{})
	requestLegalityStage.AddLogics(requestLegalityChooseLogic)

	//------prepare - Other 阶段--------
	var stageInitPrepare = zagHandler.NewZagStageDeclare(conf.PrepareInitStage).AddPres(requestLegalityStage)
	// 加载apollo远程 召回方案(默认 知乎+Bing)
	var loadApolloConfig = zagHandler.NewZagLogicDeclare(conf.LoadApolloConfig).SetClass(prepare2.LoadApolloConfigLogic{})
	// request config
	var requestConfig = zagHandler.NewZagLogicDeclare(conf.RequestConfigLogic).SetClass(prepare.RequestConfigLogic{}).AddPreLogic(loadApolloConfig)
	var initEmptyConfig = zagHandler.NewZagLogicDeclare(conf.PrepareInitEmptyLogic).SetClass(empty.EmptyLogic{})
	stageInitPrepare.AddLogics(loadApolloConfig, requestConfig, initEmptyConfig)

	//------请求缓存--------
	var cacheStage = zagHandler.NewZagStageDeclare(conf.CacheStage).AddPres(stageInitPrepare)
	var chatCacheChoose = zagHandler.NewZagLogicDeclare(conf.ChatCacheChooseLogic).SetClass(chat_cache.ChatCacheChooseLogic{})
	cacheStage.AddLogics(chatCacheChoose)

	//------命中缓存 & 非法请求--------
	var hitCacheOrIllegalRequestStage = zagHandler.NewZagStageDeclare(conf.HitCacheOrIllegalRequestStage)
	var hitCache = zagHandler.NewZagLogicDeclare(conf.HitCacheLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(chatCacheChoose)
	var illegalRequest = zagHandler.NewZagLogicDeclare(conf.IllegalRequestLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(requestLegalityChooseLogic)
	hitCacheOrIllegalRequestStage.AddLogics(hitCache, illegalRequest)

	//------未命中缓存--------
	var missCacheStage = zagHandler.NewZagStageDeclare(conf.MissCacheStage)
	var missCache = zagHandler.NewZagLogicDeclare(conf.MissCacheLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(chatCacheChoose)
	missCacheStage.AddLogics(missCache)

	//------prepare  阶段--------
	var stageOtherPrepare = zagHandler.NewZagStageDeclare(conf.PrepareOtherStage).AddPres(missCacheStage)
	// 用户标签
	var memberTagCore = zagHandler.NewZagLogicDeclare(conf.MemberTagCoreLogic).SetClass(root.MemberTagCoreV2Logic{})
	// sessionInfo
	var sessionInfo = zagHandler.NewZagLogicDeclare(conf.SessionInfoLogic).SetClass(root.SessionInfoLogic{})
	// 历史记录
	var chatHistory = zagHandler.NewZagLogicDeclare(conf.ChatHistoryLogic).SetClass(root.ChatHistoryLogic{})
	stageOtherPrepare.AddLogics(sessionInfo, memberTagCore, chatHistory)

	//------prepare - Meta阶段--------
	var stageMetaPrepare = zagHandler.NewZagStageDeclare(conf.PrepareMetaStage).AddPres(missCacheStage)
	var universalBaseInfo = zagHandler.NewZagLogicDeclare(conf.UniversalKnowledgeBaseInfoLogic).SetClass(prepare3.UniversalBaseInfoLogic{})
	var preparerDataTidy = zagHandler.NewZagLogicDeclare(conf.PreparerDataTidyLogic).SetClass(prepare3.PreparerDataTidyLogic{}).
		AddPreLogic(universalBaseInfo)
	stageMetaPrepare.AddLogics(universalBaseInfo, preparerDataTidy)

	//------prepare阶段后空算子 保障流程图可以编排使用--------
	var emptyPrepareStage = zagHandler.NewZagStageDeclare(conf.EmptyPrepareStageLogic).AddPres(missCacheStage)
	var emptyPrepare = zagHandler.NewZagLogicDeclare(conf.EmptyPrepareLogic).SetClass(empty.EmptyLogic{})
	emptyPrepareStage.AddLogics(emptyPrepare)

	//------prepare End --------
	var emptyPrepareEndStage = zagHandler.NewZagStageDeclare(conf.EmptyPrepareEndStage).AddPres(stageOtherPrepare).AddPres(stageMetaPrepare).AddPres(emptyPrepareStage)
	var EmptyPrepareEnd = zagHandler.NewZagLogicDeclare(conf.EmptyPrepareEndLogic).SetClass(empty.EmptyLogic{})
	emptyPrepareEndStage.AddLogics(EmptyPrepareEnd)

	//------ Query 安全模块--------
	var querySecurityStage = zagHandler.NewZagStageDeclare(conf.QuerySecurityStage)
	var querySecurity = zagHandler.NewZagLogicDeclare(conf.QuerySecurityLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(missCache)
	querySecurityStage.AddLogics(querySecurity)

	var securityStage = zagHandler.NewZagStageDeclare(conf.SecurityStage)
	var redLine = zagHandler.NewZagLogicDeclare(conf.RedLineLogic).SetClass(security.RedLineLogic{}).AddPreLogic(querySecurity)
	var securityReview = zagHandler.NewZagLogicDeclare(conf.SecurityReviewLogic).SetClass(security.SecurityReviewLogic{}).AddPreLogic(querySecurity)
	var faq = zagHandler.NewZagLogicDeclare(conf.FaqLogic).SetClass(security.FAQLogic{}).AddPreLogic(querySecurity)
	securityStage.AddLogics(redLine, securityReview, faq)

	var securityJudgeStage = zagHandler.NewZagStageDeclare(conf.SecurityJudgeStage).AddPres(emptyPrepareEndStage, securityStage)
	var securityPost = zagHandler.NewZagLogicDeclare(conf.SecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{})
	securityJudgeStage.AddLogics(securityPost)

	var querySecurityUnPassedStage = zagHandler.NewZagStageDeclare(conf.QuerySecurityUnPassedStage).AddPres(securityJudgeStage)
	var querySecurityUnPassedLogic = zagHandler.NewZagLogicDeclare(conf.QuerySecurityUnPassedLogic).
		SetClass(empty.EmptyLogic{})
	querySecurityUnPassedStage.AddLogics(querySecurityUnPassedLogic)

	// ------ Agent Router ----------
	var agentJudgeStage = zagHandler.NewZagStageDeclare(conf.AgentJudgeStage).AddPres(securityJudgeStage)
	var agentRouter = zagHandler.NewZagLogicDeclare(conf.AgentRouterLogic).SetClass(router.AgentRouterLogic{})
	agentJudgeStage.AddLogics(agentRouter)

	//------响应阶段--------
	var stageResponse = zagHandler.NewZagStageDeclare(conf.ResponseStage).AddPres(hitCacheOrIllegalRequestStage, querySecurityUnPassedStage, agentJudgeStage)
	var buildResponse = zagHandler.NewZagLogicDeclare(conf.ResponseLogic).SetClass(response.BuildResponseLogic{})
	var saveDialog = zagHandler.NewZagLogicDeclare(conf.SaveDialogLogic).SetClass(consumer.SaveDialogRecordLogic{}).AddPreLogic(buildResponse)
	var tracingRecordLogic = zagHandler.NewZagLogicDeclare(conf.TracingRecordLogic).SetClass(finalizer.TracingRecordLogic{}).AddPreLogic(buildResponse)
	var lastNRecordLogic = zagHandler.NewZagLogicDeclare(conf.LastNRecordLogic).SetClass(finalizer.LastNRecordLogic{}).AddPreLogic(buildResponse)
	var saveQueryResultLogic = zagHandler.NewZagLogicDeclare(conf.SaveQueryResultLogic).SetClass(finalizer.SaveQueryResultLogic{}).AddPreLogic(buildResponse)
	stageResponse.AddLogics(buildResponse, saveDialog, tracingRecordLogic, lastNRecordLogic, saveQueryResultLogic)

	// 非法判断条件边
	requestLegalityChooseLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {loadApolloConfig.Name, initEmptyConfig.Name},
		entities.Break:  {illegalRequest.Name},
	})
	// 缓存判断条件边
	chatCacheChoose.SetSelectEdge(map[string][]string{
		entities.HitCache:  {hitCache.Name},
		entities.MissCache: {missCache.Name},
	})

	// query security
	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {agentRouter.Name},
		entities.Break:  {querySecurityUnPassedLogic.Name},
	})

	stages := []*zagHandler.DeclareStage{
		// config
		initConfigStage,
		// root \ requestLegalityStage \ cacheStage
		stageRoot, requestLegalityStage, cacheStage, hitCacheOrIllegalRequestStage, missCacheStage,
		// prepare
		stageInitPrepare, stageOtherPrepare, stageMetaPrepare, emptyPrepareStage, emptyPrepareEndStage,
		// query security
		querySecurityStage, securityStage, securityJudgeStage, querySecurityUnPassedStage,
		// query router
		agentJudgeStage,
		// response
		stageResponse,
	}

	// 为算子添加 config
	for _, stage := range stages {
		for _, logic := range stage.LogicsPre {
			logic.AddConfigs(conf.StaticConfigMap[logic.Name])
		}
	}

	//把base算子、流程声明 加载到图中
	zagGraph.AddStagesWithLogics(stages...)

	//-------api 声明 >> 业务逻辑图-------
	return zagHandler.ApiDeclare2Graph[C, U, I](zagGraph)
}
