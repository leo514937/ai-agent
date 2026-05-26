package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/finalizer"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/mcp/graph/conf_stage"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/mcp/graph/logic/choose"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/mcp/graph/logic/retrieval"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/mcp/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	conf2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/query_merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/filter"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	frameworkFilter "git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// ZhidaMCPGraph 直答对外提供 MCP 服务
func ZhidaMCPGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var apiConfigPath = zagHandler.GetApiConfigPath()
	var zagGraph = zagHandler.NewZagGraphDeclareWithInfo("zhida_mcp_graph", entities.BuildGraphScene(graph_constant.ApiStreamChat, proto.ChatType_ZHIDA_MCP.String()), "1.0", "wangran", "直答 MCP 图", apiConfigPath)
	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare(conf.RootStage)
	var userMessage = zagHandler.NewZagLogicDeclare(conf.UserMessageLogic).SetClass(root.UserMessageLogic{}).SetStore(conf2.SourceQueryItemLogicStoreKey.String())
	var initConfig = zagHandler.NewZagLogicDeclare(conf.InitConfigLogic).SetClass(mapping.StageConfigLogic{}).AddPreLogic(userMessage)
	stageRoot.AddLogics(userMessage, initConfig)

	//------请求参数合法校验------
	var requestLegalityStage = zagHandler.NewZagStageDeclare(conf.RequestLegalityStage).AddPres(stageRoot)
	var requestKeyLegalityChooseLogic = zagHandler.NewZagLogicDeclare(conf.RequestKeyLegalityLogic).SetClass(choose.RequestKeyVerifyLogic{})
	requestLegalityStage.AddLogics(requestKeyLegalityChooseLogic)

	//------ Query 安全模块--------
	var querySecurityStage = zagHandler.NewZagStageDeclare(conf.QuerySecurityStage).AddPres(requestLegalityStage)
	var querySecurity = zagHandler.NewZagLogicDeclare(conf.QuerySecurityLogic).SetClass(empty.EmptyLogic{})
	var redLine = zagHandler.NewZagLogicDeclare(conf.RedLineLogic).SetClass(security.RedLineLogic{}).AddPreLogic(querySecurity)
	var securityReview = zagHandler.NewZagLogicDeclare(conf.SecurityReviewLogic).SetClass(security.SecurityReviewLogic{}).AddPreLogic(querySecurity)
	var faq = zagHandler.NewZagLogicDeclare(conf.FaqLogic).SetClass(security.FAQLogic{}).AddPreLogic(querySecurity)
	var securityPost = zagHandler.NewZagLogicDeclare(conf.SecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(redLine).AddPreLogic(securityReview).AddPreLogic(faq)
	querySecurityStage.AddLogics(querySecurity, redLine, securityReview, faq, securityPost)

	// ------ Query Router ----------
	var mergeAndRouteStage = zagHandler.NewZagStageDeclare(conf.AgentJudgeStage).AddPres(requestLegalityStage)
	var queryMerge = zagHandler.NewZagLogicDeclare(conf.EmptyQueryMergeLogic).SetClass(query_merge.QueryMergeLogic{})
	var queryRoute = zagHandler.NewZagLogicDeclare(conf.QueryRouterLogic).SetClass(meta_fetcher.QueryRouterLogic{})
	mergeAndRouteStage.AddLogics(queryRoute, queryMerge)

	//------召回--------
	var recallStage = zagHandler.NewZagStageDeclare(conf.KbRecallStage).AddPres(mergeAndRouteStage)
	var recallConfigLogic = zagHandler.NewZagLogicDeclare(conf.RecallConfigLogic).SetClass(mapping.StageConfigLogic{})
	var kbKexinRecall = zagHandler.NewZagLogicDeclare(conf.KbKexinRecallLogic).SetClass(recall.KbOutSiteRecallLogic{}).AddPreLogic(recallConfigLogic)
	// 过滤
	var recallInitFilter = zagHandler.NewZagLogicDeclare(conf.RecallInitFilterLogic).SetClass(frameworkFilter.InitFilterLogic[any, any, any]{}).AddPreLogic(kbKexinRecall)
	// 内容黑名单过滤 KbRecallBlackListFilterLogic
	var recallBlacklistFetcher = zagHandler.NewZagLogicDeclare(conf.RecallBlackListFilterLogic).SetClass(filter.KbRecallBlackListFilterLogic{}).AddPreLogic(recallInitFilter)
	// 内容安全过滤
	var recallSecurityValidContentFetcher = zagHandler.NewZagLogicDeclare(conf.RecallSecurityValidContentFetcherLogic).SetClass(security.SecurityReviewRecallLogic{}).
		AddPreLogic(recallInitFilter)
	var recallSecurityContentFilter = zagHandler.NewZagLogicDeclare(conf.RecallSecurityContentFilterLogic).SetClass(filter.KbRecallSecurityFilterLogic{}).
		AddPreLogic(recallSecurityValidContentFetcher)
	var recallPostFilter = zagHandler.NewZagLogicDeclare(conf.RecallPostFilterLogic).SetClass(frameworkFilter.FilterPostLogic[any, any, any]{}).
		AddPreLogic(recallSecurityContentFilter).AddPreLogic(recallBlacklistFetcher)
	var recallLimitLogic = zagHandler.NewZagLogicDeclare(conf.RecallLimitLogic).SetClass(retrieval.ZhidaMCPRecallLimitLogic{}).AddPreLogic(recallPostFilter)
	recallStage.AddLogics(recallConfigLogic, kbKexinRecall, recallInitFilter, recallBlacklistFetcher, recallSecurityValidContentFetcher, recallSecurityContentFilter, recallPostFilter, recallLimitLogic)

	//------召回与Query 最终判断安全模块--------
	var recallAndSafetyJudgeChooseStage = zagHandler.NewZagStageDeclare(conf.RecallAndSafetyJudgeChooseStage).AddPres(recallStage).AddPres(querySecurityStage)
	var recallAndSafetyJudgeChoose = zagHandler.NewZagLogicDeclare(conf.RecallAndSafetyJudgeChooseLogic).
		SetClass(security_post.RecallAndSafetyJudgeChoose{}).AddPreLogic(securityPost)
	recallAndSafetyJudgeChooseStage.AddLogics(recallAndSafetyJudgeChoose)

	//------空算子(安全未通过)--------
	var recallAndSafetyUnPassedStage = zagHandler.NewZagStageDeclare(conf.RecallAndSafetyUnPassedStage)
	var recallAndSafetyUnPassedLogic = zagHandler.NewZagLogicDeclare(conf.RecallAndSafetyUnPassedLogic).
		SetClass(empty.EmptyLogic{}).AddPreLogic(recallAndSafetyJudgeChoose)
	recallAndSafetyUnPassedStage.AddLogics(recallAndSafetyUnPassedLogic)
	// 命中faq后判断是否展示召回内容
	var uploadRecallChanThenBreakStage = zagHandler.NewZagStageDeclare(conf.UploadRecallChanThenBreakStage)
	var uploadRecallChanThenBreak = zagHandler.NewZagLogicDeclare(conf.UploadRecallChanThenBreakLogic).SetClass(response.UploadRespChanLogic{}).
		AddPreLogic(recallAndSafetyJudgeChoose)
	uploadRecallChanThenBreakStage.AddLogics(uploadRecallChanThenBreak)

	// 发送Recall 结果到 chan
	var uploadRecallChanStage = zagHandler.NewZagStageDeclare(conf.UploadRecallChanStage)
	var uploadRecallChan = zagHandler.NewZagLogicDeclare(conf.UploadRecallChanLogic).SetClass(response.UploadRespChanLogic{}).
		AddPreLogic(recallAndSafetyJudgeChoose)
	uploadRecallChanStage.AddLogics(uploadRecallChan)

	// 生成阶段配置
	var generateConfigStage = zagHandler.NewZagStageDeclare(conf.GenerateConfigStage).AddPres(uploadRecallChanStage)
	var generateConfigLogic = zagHandler.NewZagLogicDeclare(conf.GenerateConfigLogic).SetClass(mapping.StageConfigLogic{})
	generateConfigStage.AddLogics(generateConfigLogic)

	//------answer 生成阶段--------
	var stageGenerate = zagHandler.NewZagStageDeclare(conf.GenerateStage).AddPres(generateConfigStage)
	var streamChatLogic = zagHandler.NewZagLogicDeclare(conf.StreamChatLogic).SetClass(generate.StreamChatLogic{}).
		SetTimeOut(600 * 1000)
	stageGenerate.AddLogics(streamChatLogic)

	//------answer 安全审核--------
	var answerSecurityStage = zagHandler.NewZagStageDeclare(conf.AnswerSecurityStage)
	var answerSecurityPostBeforeLogic = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityBeforePostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(streamChatLogic).SetStore(conf2.StreamChatResultStoreKey.String())
	var securityReviewOut = zagHandler.NewZagLogicDeclare(conf.SecurityReviewOutLogic).SetClass(security.SecurityReviewLogic{}).
		AddPreLogic(answerSecurityPostBeforeLogic)
	// 如果有幸进入这里 则需需要二次更新 ResultStoreKey
	var answerSecurityPostLogic = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(securityReviewOut).SetStore(conf2.StreamChatResultStoreKey.String())
	answerSecurityStage.AddLogics(answerSecurityPostBeforeLogic, securityReviewOut, answerSecurityPostLogic)

	//------answer 安全审核--------
	var answerSecurityUnPassStage = zagHandler.NewZagStageDeclare(conf.AnswerSecurityUnPassStage)
	var answerSecurityBeforeUnPass = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityBeforeUnPassLogic).
		SetClass(empty.EmptyLogic{}).AddPreLogic(answerSecurityPostBeforeLogic)
	var answerSecurityUnPass = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityUnPassLogic).
		SetClass(empty.EmptyLogic{}).AddPreLogic(answerSecurityPostLogic)
	answerSecurityUnPassStage.AddLogics(answerSecurityBeforeUnPass, answerSecurityUnPass)

	//------word 生成阶段--------
	var stageWordGenerate = zagHandler.NewZagStageDeclare(conf.WordGenerateStage).AddPres(generateConfigStage)
	var chatLogic = zagHandler.NewZagLogicDeclare(conf.ChatLogic).SetClass(generate.ChatLogic{}).SetTimeOut(600 * 1000)
	var chatAnswer2SentenceLogic = zagHandler.NewZagLogicDeclare(conf.Answer2SentenceLogic).SetClass(mapping.ChatAnswer2SentenceLogic{}).AddPreLogic(chatLogic)
	stageWordGenerate.AddLogics(chatLogic, chatAnswer2SentenceLogic)

	//------word 安全审核--------
	var wordSecurityStage = zagHandler.NewZagStageDeclare(conf.WordSecurityStage)
	var wordSecurityReviewLogic = zagHandler.NewZagLogicDeclare(conf.RelevantQuerySecurityReviewLogic).SetClass(security.SecurityReviewWordLogic{}).
		AddPreLogic(chatAnswer2SentenceLogic)
	var wordSecurityPostLogic = zagHandler.NewZagLogicDeclare(conf.RelevantQuerySecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(wordSecurityReviewLogic)
	var uploadRespChanLogic = zagHandler.NewZagLogicDeclare(conf.UploadQueryChanLogic).SetClass(response.UploadRespChanLogic{}).
		AddPreLogic(wordSecurityPostLogic)
	wordSecurityStage.AddLogics(wordSecurityReviewLogic, wordSecurityPostLogic, uploadRespChanLogic)

	//------响应阶段--------
	var stageResponse = zagHandler.NewZagStageDeclare(conf.ResponseStage).AddPres(requestLegalityStage, recallAndSafetyUnPassedStage, uploadRecallChanThenBreakStage, answerSecurityStage, answerSecurityUnPassStage, wordSecurityStage)
	var BuildResponse = zagHandler.NewZagLogicDeclare(conf.ResponseLogic).SetClass(response.BuildResponseLogic{})
	var tracingRecordLogic = zagHandler.NewZagLogicDeclare(conf.TracingRecordLogic).SetClass(finalizer.TracingRecordLogic{}).AddPreLogic(BuildResponse)
	stageResponse.AddLogics(BuildResponse, tracingRecordLogic)

	// 非法判断条件边
	requestKeyLegalityChooseLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {querySecurity.Name, queryRoute.Name, queryMerge.Name},
		entities.Break:  {BuildResponse.Name},
	})

	// query 和 query merge 安全模块条件边
	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {recallAndSafetyJudgeChoose.Name},
		entities.Break:  {recallAndSafetyJudgeChoose.Name},
	})

	recallAndSafetyJudgeChoose.SetSelectEdge(map[string][]string{
		entities.Normal:                {uploadRecallChan.Name},
		entities.Break:                 {recallAndSafetyUnPassedLogic.Name},
		entities.UploadRecallThenBreak: {uploadRecallChanThenBreak.Name},
	})

	answerSecurityPostBeforeLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {securityReviewOut.Name},
		entities.Break:  {answerSecurityBeforeUnPass.Name},
	})
	answerSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {BuildResponse.Name},
		entities.Break:  {answerSecurityUnPass.Name},
	})
	wordSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {uploadRespChanLogic.Name},
		entities.Break:  {uploadRespChanLogic.Name},
	})

	stages := []*zagHandler.DeclareStage{
		// config
		generateConfigStage,
		// root
		stageRoot,
		// legality
		requestLegalityStage,
		// route
		mergeAndRouteStage,
		// query security
		querySecurityStage,
		// recall
		recallStage,
		// judge
		recallAndSafetyJudgeChooseStage, recallAndSafetyUnPassedStage, uploadRecallChanThenBreakStage, uploadRecallChanStage,
		// generate
		stageGenerate, stageWordGenerate,
		// security
		answerSecurityStage, answerSecurityUnPassStage, wordSecurityStage,
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
