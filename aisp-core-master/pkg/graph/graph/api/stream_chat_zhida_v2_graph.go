package api

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/finalizer"
	prepare2 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/prepare"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/conf_stage"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/logic/prepare"
	prepare3 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/logic/prepare"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/logic/retrieval"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/chat_cache"
	choose2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/choose"
	conf2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/consumer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/query_merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// StreamChatZhiDaV2Graph 直答 2.0
func StreamChatZhiDaV2Graph[C, U, I any](bizType string) *graph.Graph {
	//========图声明========
	var apiConfigPath = zagHandler.GetApiConfigPath()
	var zagGraph = zagHandler.NewZagGraphDeclareWithInfo("chat_graph", entities.BuildGraphScene(graph_constant.ApiStreamChat, bizType), "2.7", "zhoupengcheng,wanghao11,wangran,keyan01", "直答V2.0", apiConfigPath)

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

	//------prepare - Other 阶段--------
	var stageOtherPrepare = zagHandler.NewZagStageDeclare(conf.PrepareOtherStage).AddPres(missCacheStage)
	// 用户标签
	var memberTagCore = zagHandler.NewZagLogicDeclare(conf.MemberTagCoreLogic).SetClass(root.MemberTagCoreV2Logic{})
	// sessionInfo
	var sessionInfo = zagHandler.NewZagLogicDeclare(conf.SessionInfoLogic).SetClass(root.SessionInfoLogic{})
	// 历史记录
	var chatHistory = zagHandler.NewZagLogicDeclare(conf.ChatHistoryLogic).SetClass(root.ChatHistoryLogic{})
	// 名词解释
	var queryDefinition = zagHandler.NewZagLogicDeclare(conf.QueryDefinitionLogic).SetClass(prepare2.QueryDefinitionLogic{})
	stageOtherPrepare.AddLogics(sessionInfo, memberTagCore, chatHistory, queryDefinition)

	//------prepare - Meta阶段--------
	var stageMetaPrepare = zagHandler.NewZagStageDeclare(conf.PrepareMetaStage).AddPres(missCacheStage)
	var knowledgeBaseInfo = zagHandler.NewZagLogicDeclare(conf.KnowledgeBaseInfoLogic).SetClass(root.KnowledgeBaseInfoLogic{})
	var authorMetaInfo = zagHandler.NewZagLogicDeclare(conf.AuthorMetaInfoLogic).SetClass(root.MembersInfoLogic{}).AddPreLogic(requestConfig)
	var universalBaseInfo = zagHandler.NewZagLogicDeclare(conf.UniversalKnowledgeBaseInfoLogic).SetClass(prepare3.UniversalBaseInfoLogic{})
	stageMetaPrepare.AddLogics(knowledgeBaseInfo, authorMetaInfo, universalBaseInfo)

	//------prepare阶段后空算子 保障流程图可以编排使用--------
	var emptyPrepareStage = zagHandler.NewZagStageDeclare(conf.EmptyPrepareStageLogic).AddPres(missCacheStage)
	var emptyPrepare = zagHandler.NewZagLogicDeclare(conf.EmptyPrepareLogic).SetClass(empty.EmptyLogic{})
	emptyPrepareStage.AddLogics(emptyPrepare)

	//------prepare End --------
	var emptyPrepareEndStage = zagHandler.NewZagStageDeclare(conf.EmptyPrepareEndStage).AddPres(stageOtherPrepare).AddPres(stageMetaPrepare).AddPres(emptyPrepareStage)
	var EmptyPrepareEnd = zagHandler.NewZagLogicDeclare(conf.EmptyPrepareEndLogic).SetClass(empty.EmptyLogic{})
	emptyPrepareEndStage.AddLogics(EmptyPrepareEnd)

	// ------ Query Router ----------
	var agentJudgeStage = zagHandler.NewZagStageDeclare(conf.AgentJudgeStage).AddPres(emptyPrepareEndStage)
	var queryRoute = zagHandler.NewZagLogicDeclare(conf.QueryRouterLogic).SetClass(meta_fetcher.QueryRouterLogic{})
	agentJudgeStage.AddLogics(queryRoute)

	//------QueryMerge阶段--------
	var stageQueryMerge = zagHandler.NewZagStageDeclare(conf.QueryMergeStage).AddPres(emptyPrepareEndStage)
	var queryMerge = zagHandler.NewZagLogicDeclare(conf.QueryMergeLogic).SetClass(query_merge.QueryMergeLogic{})
	stageQueryMerge.AddLogics(queryMerge)

	//------ Query & QueryMerge 安全模块--------
	var querySecurityStage = zagHandler.NewZagStageDeclare(conf.QuerySecurityStage)
	var querySecurity = zagHandler.NewZagLogicDeclare(conf.QuerySecurityLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(missCache)
	var queryMergeSecurity = zagHandler.NewZagLogicDeclare(conf.QueryMergeSecurityLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(queryMerge)
	querySecurityStage.AddLogics(querySecurity, queryMergeSecurity)

	var securityStage = zagHandler.NewZagStageDeclare(conf.SecurityStage)
	// query
	var redLine = zagHandler.NewZagLogicDeclare(conf.RedLineLogic).SetClass(security.RedLineLogic{}).AddPreLogic(querySecurity)
	var securityReview = zagHandler.NewZagLogicDeclare(conf.SecurityReviewLogic).SetClass(security.SecurityReviewLogic{}).AddPreLogic(querySecurity)
	var faq = zagHandler.NewZagLogicDeclare(conf.FaqLogic).SetClass(security.FAQLogic{}).AddPreLogic(querySecurity)
	var securityPost = zagHandler.NewZagLogicDeclare(conf.SecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(redLine).AddPreLogic(securityReview).AddPreLogic(faq)
	// queryMerge
	var redLineM = zagHandler.NewZagLogicDeclare(conf.RedLineMLogic).SetClass(security.RedLineLogic{}).AddPreLogic(queryMergeSecurity)
	var securityReviewM = zagHandler.NewZagLogicDeclare(conf.SecurityReviewMLogic).SetClass(security.SecurityReviewLogic{}).AddPreLogic(queryMergeSecurity)
	var faqM = zagHandler.NewZagLogicDeclare(conf.FaqMLogic).SetClass(security.FAQLogic{}).AddPreLogic(queryMergeSecurity)
	var securityPostM = zagHandler.NewZagLogicDeclare(conf.SecurityPostMLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(redLineM).AddPreLogic(securityReviewM).AddPreLogic(faqM)
	securityStage.AddLogics(redLine, securityReview, faq, securityPost, redLineM, securityReviewM, faqM, securityPostM)

	//------召回子图--------
	var subGraphRecallStage = zagHandler.NewZagStageDeclare(conf.SubGraphRecallStage).AddPres(stageQueryMerge).AddPres(agentJudgeStage)
	var subGraphRecallBeginLogic = zagHandler.NewZagLogicDeclare(conf.SubGraphRecallBeginLogic).SetClass(retrieval.RefProducerBeginLogic{})
	var subGraphRecallLogic = zagHandler.NewZagLogicDeclare(conf.SubGraphRecallLogic).SetClass(logic.SubGraphRecallLogic{}).SetStore(conf2.RecallCardLogicStoreKey.String()).AddPreLogic(subGraphRecallBeginLogic)
	subGraphRecallStage.AddLogics(subGraphRecallBeginLogic, subGraphRecallLogic)

	// Rerank阶段配置
	var rerankConfigStage = zagHandler.NewZagStageDeclare(conf.RerankConfigStage).AddPres(subGraphRecallStage)
	var rerankConfigLogic = zagHandler.NewZagLogicDeclare(conf.RerankConfigLogic).SetClass(mapping.StageConfigLogic{})
	rerankConfigStage.AddLogics(rerankConfigLogic)

	// Rerank阶段
	var rerankStage = zagHandler.NewZagStageDeclare(conf.RerankStage).AddPres(rerankConfigStage)
	// 确定角标和输出内容
	var rerankBefore = zagHandler.NewZagLogicDeclare(conf.RerankBeforeLogic).SetClass(rerank.KbRecallChunkAndReRankV2BeforeLogic{})
	// 分chunk和评分(新)
	var recallChunkAndScore = zagHandler.NewZagLogicDeclare(conf.RecallChunkAndScoreLogic).
		SetClass(rerank.KbRecallChunkAndScoreLogic{}).AddPreLogic(rerankBefore)
	var reRankAfter = zagHandler.NewZagLogicDeclare(conf.RerankAfterLogic).
		SetClass(rerank.KbRecallChunkAndReRankV2AfterLogic{}).AddPreLogic(recallChunkAndScore).SetStore(conf2.RecallCardLogicStoreKey.String())
	rerankStage.AddLogics(rerankBefore, recallChunkAndScore, reRankAfter)

	//------召回与Query 最终判断安全模块--------
	var recallAndSafetyJudgeChooseStage = zagHandler.NewZagStageDeclare(conf.RecallAndSafetyJudgeChooseStage)
	var recallAndSafetyJudgeChoose = zagHandler.NewZagLogicDeclare(conf.RecallAndSafetyJudgeChooseLogic).
		SetClass(security_post.RecallAndSafetyJudgeChoose{}).AddPreLogic(securityPost).AddPreLogic(securityPostM).AddPreLogic(reRankAfter)
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
	var stageWordGenerate = zagHandler.NewZagStageDeclare(conf.WordGenerateStage)
	var recallRebootResp = zagHandler.NewZagLogicDeclare(conf.RecallRebootRespLogic).SetClass(recall.KbRecallRebootRespLogic{}).AddPreLogic(answerSecurityPostLogic)
	var chatLogic = zagHandler.NewZagLogicDeclare(conf.ChatLogic).SetClass(generate.ChatLogic{}).SetTimeOut(600 * 1000).AddPreLogic(recallRebootResp)
	var chatAnswer2SentenceLogic = zagHandler.NewZagLogicDeclare(conf.Answer2SentenceLogic).SetClass(mapping.ChatAnswer2SentenceLogic{}).AddPreLogic(chatLogic)
	stageWordGenerate.AddLogics(recallRebootResp, chatLogic, chatAnswer2SentenceLogic)

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
	var stageResponse = zagHandler.NewZagStageDeclare(conf.ResponseStage).AddPres(hitCacheOrIllegalRequestStage, recallAndSafetyUnPassedStage, uploadRecallChanThenBreakStage, answerSecurityUnPassStage, wordSecurityStage)
	var BuildResponse = zagHandler.NewZagLogicDeclare(conf.ResponseLogic).SetClass(response.BuildResponseLogic{})

	var saveDialog = zagHandler.NewZagLogicDeclare(conf.SaveDialogLogic).SetClass(consumer.SaveDialogRecordLogic{}).AddPreLogic(BuildResponse)
	var tracingRecordLogic = zagHandler.NewZagLogicDeclare(conf.TracingRecordLogic).SetClass(finalizer.TracingRecordLogic{}).AddPreLogic(BuildResponse)
	var lastNRecordLogic = zagHandler.NewZagLogicDeclare(conf.LastNRecordLogic).SetClass(finalizer.LastNRecordLogic{}).AddPreLogic(BuildResponse)
	var saveQueryResultLogic = zagHandler.NewZagLogicDeclare(conf.SaveQueryResultLogic).SetClass(finalizer.SaveQueryResultLogic{}).AddPreLogic(BuildResponse)
	stageResponse.AddLogics(BuildResponse, saveDialog, tracingRecordLogic, lastNRecordLogic, saveQueryResultLogic)

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

	// query 和 query merge 安全模块条件边
	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {recallAndSafetyJudgeChoose.Name},
		entities.Break:  {recallAndSafetyJudgeChoose.Name},
	})
	securityPostM.SetSelectEdge(map[string][]string{
		entities.Normal: {recallAndSafetyJudgeChoose.Name},
		entities.Break:  {recallAndSafetyJudgeChoose.Name},
	})

	recallAndSafetyJudgeChoose.SetSelectEdge(map[string][]string{
		entities.Normal: {uploadRecallChan.Name},
		// break 或 命中 faq 直接跳过模型回答
		entities.Break:                 {recallAndSafetyUnPassedLogic.Name},
		entities.UploadRecallThenBreak: {uploadRecallChanThenBreak.Name},
	})

	answerSecurityPostBeforeLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {securityReviewOut.Name},
		entities.Break:  {answerSecurityBeforeUnPass.Name},
	})

	answerSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {recallRebootResp.Name},
		entities.Break:  {answerSecurityUnPass.Name},
	})
	wordSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {uploadRespChanLogic.Name},
		entities.Break:  {uploadRespChanLogic.Name},
	})

	stages := []*zagHandler.DeclareStage{
		// config
		initConfigStage, rerankConfigStage, generateConfigStage,
		// root \ requestLegalityStage \ cacheStage
		stageRoot, requestLegalityStage, cacheStage, hitCacheOrIllegalRequestStage, missCacheStage,
		// prepare
		stageInitPrepare, stageOtherPrepare, stageMetaPrepare, emptyPrepareStage, emptyPrepareEndStage,
		// query router
		agentJudgeStage,
		// query or query merge security
		querySecurityStage, securityStage, stageQueryMerge,
		// recall
		subGraphRecallStage,
		// rerank
		rerankStage,
		// judge
		recallAndSafetyJudgeChooseStage, recallAndSafetyUnPassedStage, uploadRecallChanThenBreakStage, uploadRecallChanStage,
		// generate
		stageGenerate, stageWordGenerate,
		// response
		answerSecurityStage, answerSecurityUnPassStage, wordSecurityStage, stageResponse,
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
