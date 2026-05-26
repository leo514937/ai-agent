package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/finalizer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/prepare"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/judge"
	mapping2 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/mapping"
	meta_fetcher2 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/meta_fetcher"
	zhidaProPrepare "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/prepare"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/retrieval"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
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
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/filter"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	frameworkFilter "git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// StreamChatZhidaProGraph 专业版直答
func StreamChatZhidaProGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var apiConfigPath = zagHandler.GetApiConfigPath()
	var zagGraph = zagHandler.NewZagGraphDeclareWithInfo("chat_graph", entities.BuildGraphScene(graph_constant.ApiStreamChat, proto.ChatType_ZHIDA_PRO_TAB.String()), "1.19", "zhoupengcheng,wanghao11,wangran,keyan01", "直答专业版图", apiConfigPath)
	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare(conf.RootStage)
	var copyUserMeta = zagHandler.NewZagLogicDeclare(conf.CopyUserMetaLogic).SetClass(root.CopyUserMetaLogic{})
	var UserMessage = zagHandler.NewZagLogicDeclare(conf.UserMessageLogic).SetClass(root.UserMessageLogic{}).SetStore(conf2.SourceQueryItemLogicStoreKey.String()).
		AddPreLogic(copyUserMeta)
	stageRoot.AddLogics(copyUserMeta, UserMessage)

	//------prepare阶段--------
	var stagePrepare = zagHandler.NewZagStageDeclare(conf.PrepareStage).AddPres(stageRoot)
	// 加载apollo远程 召回方案(默认 知乎+Bing)
	var loadApolloConfig = zagHandler.NewZagLogicDeclare(conf.LoadApolloConfig).SetClass(prepare.LoadApolloConfigLogic{})
	// config 参数
	var requestConfig = zagHandler.NewZagLogicDeclare(conf.RequestConfigLogic).SetClass(zhidaProPrepare.RequestConfigLogic{}).AddPreLogic(loadApolloConfig)
	// 历史记录
	var chatHistory = zagHandler.NewZagLogicDeclare(conf.ChatHistoryLogic).SetClass(root.ChatHistoryLogic{}).AddPreLogic(requestConfig)
	// sessionInfo
	var sessionInfo = zagHandler.NewZagLogicDeclare(conf.SessionInfoLogic).SetClass(root.SessionInfoLogic{}).AddPreLogic(requestConfig)
	var KnowledgeBaseInfo = zagHandler.NewZagLogicDeclare(conf.KnowledgeBaseInfoLogic).SetClass(root.KnowledgeBaseInfoLogic{}).AddPreLogic(requestConfig)
	stagePrepare.AddLogics(requestConfig, chatHistory, sessionInfo, KnowledgeBaseInfo, loadApolloConfig)

	//------prepare阶段后空算子 保障流程图可以编排使用--------
	var emptyPrepareStage = zagHandler.NewZagStageDeclare(conf.EmptyPrepareStageLogic).AddPres(stageRoot)
	var emptyPrepare = zagHandler.NewZagLogicDeclare(conf.EmptyPrepareLogic).SetClass(empty.EmptyLogic{})
	emptyPrepareStage.AddLogics(emptyPrepare)

	//------请求参数合法校验------
	var requestLegalityStage = zagHandler.NewZagStageDeclare(conf.RequestLegalityStage).AddPres(stagePrepare, emptyPrepareStage)
	var requestLegalityChooseLogic = zagHandler.NewZagLogicDeclare(conf.RequestLegalityLogic).SetClass(choose2.RequestLegalityVerifyLogic{})
	requestLegalityStage.AddLogics(requestLegalityChooseLogic)

	//------ 判断为非法请求验证--------
	var emptyStage = zagHandler.NewZagStageDeclare(conf.EmptyStage)
	var illegalRequest = zagHandler.NewZagLogicDeclare(conf.IllegalRequestLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(requestLegalityChooseLogic)
	emptyStage.AddLogics(illegalRequest)

	//------安全模块--------
	var securityStage = zagHandler.NewZagStageDeclare(conf.SecurityStage).AddPres(requestLegalityStage)
	var redLine = zagHandler.NewZagLogicDeclare(conf.RedLineLogic).SetClass(security.RedLineLogic{})
	var securityReview = zagHandler.NewZagLogicDeclare(conf.SecurityReviewLogic).SetClass(security.SecurityReviewLogic{})
	var faq = zagHandler.NewZagLogicDeclare(conf.FaqLogic).SetClass(security.FAQLogic{})
	var securityPost = zagHandler.NewZagLogicDeclare(conf.SecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(redLine).AddPreLogic(securityReview).AddPreLogic(faq)
	securityStage.AddLogics(redLine, securityReview, faq, securityPost)

	//------QueryMerge阶段--------
	var stageQueryMerge = zagHandler.NewZagStageDeclare(conf.QueryMergeStage).AddPres(requestLegalityStage)
	var queryMerge = zagHandler.NewZagLogicDeclare(conf.QueryMergeLogic).SetClass(query_merge.QueryMergeLogic{})
	stageQueryMerge.AddLogics(queryMerge)

	//------安全模块--------
	var securityStageM = zagHandler.NewZagStageDeclare(conf.SecurityMStage).AddPres(stageQueryMerge)
	var redLineM = zagHandler.NewZagLogicDeclare(conf.RedLineMLogic).SetClass(security.RedLineLogic{})
	var securityReviewM = zagHandler.NewZagLogicDeclare(conf.SecurityReviewMLogic).SetClass(security.SecurityReviewLogic{})
	var faqM = zagHandler.NewZagLogicDeclare(conf.FaqMLogic).SetClass(security.FAQLogic{})
	var securityPostM = zagHandler.NewZagLogicDeclare(conf.SecurityPostMLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(redLineM).AddPreLogic(securityReviewM).AddPreLogic(faqM)
	securityStageM.AddLogics(redLineM, securityReviewM, faqM, securityPostM)

	//------Query / QueryMerge 安全模块--------
	var queryAndQueryMergeSafetyJudgeStage = zagHandler.NewZagStageDeclare(conf.QueryAndQueryMergeSafetyJudgeStage)
	var queryAndQueryMergeSafetyJudge = zagHandler.NewZagLogicDeclare(conf.QueryAndQueryMergeSafetyJudge).
		SetClass(security_post.QueryAndQueryMergeSafetyJudge{}).AddPreLogic(securityPost).AddPreLogic(securityPostM)
	queryAndQueryMergeSafetyJudgeStage.AddLogics(queryAndQueryMergeSafetyJudge)
	//------Query / QueryMerge 安全模块 (安全未通过)--------
	var queryAndQueryMergeSafetyUnPassedStage = zagHandler.NewZagStageDeclare(conf.QueryAndQueryMergeSafetyUnPassedStage)
	var queryAndQueryMergeSafetyUnPassed = zagHandler.NewZagLogicDeclare(conf.QueryAndQueryMergeSafetyUnPassedLogic).
		SetClass(empty.EmptyLogic{}).AddPreLogic(queryAndQueryMergeSafetyJudge)
	queryAndQueryMergeSafetyUnPassedStage.AddLogics(queryAndQueryMergeSafetyUnPassed)

	// Doc路由判断
	var docRouterJudgeStage = zagHandler.NewZagStageDeclare(conf.DocRouterJudgeStage).AddPres(queryAndQueryMergeSafetyJudgeStage)
	var docRouterJudge = zagHandler.NewZagLogicDeclare(conf.DocRouterJudge).SetClass(judge.DocRouterJudgeLogic{})
	docRouterJudgeStage.AddLogics(docRouterJudge)

	// ------agent选择----------
	// 复用原有路由模型，以下模块针对「知识查询」做策略优化，其他路由结果直接复用原来的方案
	// 由于专业版暂时没涉及答主卡片，路由结果如果是「知乎答主查询」改为「知识查询」
	var agentJudgeStage = zagHandler.NewZagStageDeclare(conf.AgentJudgeStage)
	var queryRoute = zagHandler.NewZagLogicDeclare(conf.QueryRouterLogic).SetClass(meta_fetcher.QueryRouterLogic{}).AddPreLogic(docRouterJudge)
	var agentOverwriteConfig = zagHandler.NewZagLogicDeclare(conf.AgentOverwriteConfigLogic).SetClass(mapping.OverwriteConfigLogic{}).AddPreLogic(queryRoute)
	agentJudgeStage.AddLogics(queryRoute, agentOverwriteConfig)

	//------recall阶段--------
	var stageKbRecall = zagHandler.NewZagStageDeclare(conf.KbRecallStage)
	var bgeEmbeddingFetcherLogic = zagHandler.NewZagLogicDeclare(conf.BgeEmbeddingFetcherLogic).SetClass(meta_fetcher.KlaraEmbeddingFetcherLogic{}).AddPreLogic(agentOverwriteConfig)
	var bgeM3EmbeddingFetcherLogic = zagHandler.NewZagLogicDeclare(conf.BgeM3EmbeddingFetcherLogic).SetClass(meta_fetcher.KlaraEmbeddingFetcherLogic{}).AddPreLogic(agentOverwriteConfig)
	var quKeywordFetcherLogic = zagHandler.NewZagLogicDeclare(conf.QuKeywordFetcherLogic).SetClass(meta_fetcher.QuKeywordFetcherLogic{}).AddPreLogic(agentOverwriteConfig)

	var kbZhihuRecall = zagHandler.NewZagLogicDeclare(conf.KbZhihuRecallLogic).SetClass(recall.KbZhihuRecallLogic{}).AddPreLogic(agentOverwriteConfig)
	var kbArxivRecall = zagHandler.NewZagLogicDeclare(conf.KbArxivRecallLogic).SetClass(recall.KbZhihuRecallLogic{}).AddPreLogic(agentOverwriteConfig)
	var kbReplenishArxivRecall = zagHandler.NewZagLogicDeclare(conf.KbReplenishArxivRecallLogic).SetClass(recall.KbReplenishArxivRecallLogic{}).AddPreLogic(agentOverwriteConfig)
	var kbZhWikiRumRecall = zagHandler.NewZagLogicDeclare(conf.KbZhWikiRumRecallLogic).SetClass(recall.RumRecallLogic{}).AddPreLogic(bgeEmbeddingFetcherLogic)
	var kbEnWikiRumRecall = zagHandler.NewZagLogicDeclare(conf.KbEnWikiRumRecallLogic).SetClass(recall.RumRecallLogic{}).AddPreLogic(bgeEmbeddingFetcherLogic)
	var specifiedDocRecall = zagHandler.NewZagLogicDeclare(conf.SpecifiedDocRecallLogic).SetClass(retrieval.SpecifiedDocRecallLogic{}).AddPreLogic(docRouterJudge)
	var kbZhWikiRuceneRecall = zagHandler.NewZagLogicDeclare(conf.KbZhWikiRuceneRecallLogic).SetClass(recall.RuceneLogic{}).AddPreLogic(quKeywordFetcherLogic)
	var kbEnWikiRuceneRecall = zagHandler.NewZagLogicDeclare(conf.KbEnWikiRuceneRecallLogic).SetClass(recall.RuceneLogic{}).AddPreLogic(quKeywordFetcherLogic)
	var personalKnowledgeBaseRumRecall = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseRumRecallLogic).SetClass(recall.RumRecallLogic{}).AddPreLogic(bgeM3EmbeddingFetcherLogic)
	var personalKnowledgeBaseRuceneRecall = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseRuceneRecallLogic).SetClass(recall.RuceneLogic{}).AddPreLogic(quKeywordFetcherLogic)
	var internalKnowledgeBaseRumRecall = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRumRecallLogic).SetClass(recall.RumRecallLogic{}).AddPreLogic(bgeM3EmbeddingFetcherLogic)
	var internalKnowledgeBaseRuceneRecall = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRuceneRecallLogic).SetClass(recall.RuceneLogic{}).AddPreLogic(quKeywordFetcherLogic)

	//------- recall MetaFetcher---------
	var recallMetaFetcherStage = zagHandler.NewZagStageDeclare(conf.RecallMetaFetcherStage)
	// 因 kbRecallMetaFetcher 是 一个Fetcher 算子，入参只能为一个itemList，所以需要一个merge 算子 将 zhihu 和 arxiv 召回源合并
	var kbRecallMetaFetcherMerge = zagHandler.NewZagLogicDeclare(conf.KbRecallMetaFetcherMergeLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(kbZhihuRecall).AddPreLogic(kbArxivRecall).AddPreLogic(kbReplenishArxivRecall)
	var kbRecallMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).AddPreLogic(kbRecallMetaFetcherMerge)
	var contentCoreMetaFetcher = zagHandler.NewZagLogicDeclare(conf.ContentCoreMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).AddPreLogic(specifiedDocRecall)
	var contentCoreParentMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallParentMetaFetcherLogic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).AddPreLogic(contentCoreMetaFetcher)
	var personalKnowledgeBaseRecallMetaFetcherMerge = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseRecallMetaFetcherMergeLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(personalKnowledgeBaseRumRecall).AddPreLogic(personalKnowledgeBaseRuceneRecall)
	var personalKnowledgeBaseRecallMetaFetcher = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseRecallMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).AddPreLogic(personalKnowledgeBaseRecallMetaFetcherMerge)
	var internalKnowledgeBaseRecallMetaFetcherMerge = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRecallMetaFetcherMergeLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(internalKnowledgeBaseRumRecall).AddPreLogic(internalKnowledgeBaseRuceneRecall)
	var internalKnowledgeBaseRecallMetaFetcher = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRecallMetaFetcherLogic).SetClass(meta_fetcher2.InternalDocMetaFetcherLogic{}).AddPreLogic(internalKnowledgeBaseRecallMetaFetcherMerge)
	var internalKnowledgeBaseRecallSimMerge = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRecallSimMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).AddPreLogic(internalKnowledgeBaseRecallMetaFetcher)

	recallMetaFetcherStage.AddLogics(kbRecallMetaFetcherMerge, kbRecallMetaFetcher, contentCoreMetaFetcher, contentCoreParentMetaFetcher, personalKnowledgeBaseRecallMetaFetcherMerge, personalKnowledgeBaseRecallMetaFetcher,
		internalKnowledgeBaseRecallMetaFetcherMerge, internalKnowledgeBaseRecallMetaFetcher, internalKnowledgeBaseRecallSimMerge)

	var specificRecallOverwriteConfig = zagHandler.NewZagLogicDeclare(conf.SpecificRecallOverwriteConfigLogic).SetClass(mapping2.SpecifiedDocOverwriteConfigLogic{}).AddPreLogic(contentCoreParentMetaFetcher)

	var kbRecallZhihuSourceMerge = zagHandler.NewZagLogicDeclare(conf.KbRecallZhihuSourceMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(kbRecallMetaFetcher).
		AddPreLogic(kbZhWikiRumRecall).AddPreLogic(kbEnWikiRumRecall).
		AddPreLogic(kbEnWikiRuceneRecall).AddPreLogic(kbZhWikiRuceneRecall)
	var personalKnowledgeBaseMergeLogic = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(personalKnowledgeBaseRecallMetaFetcher)
	var kbRecallFinalSourceMerge = zagHandler.NewZagLogicDeclare(conf.KbRecallFinalSourceMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(kbRecallZhihuSourceMerge).AddPreLogic(personalKnowledgeBaseMergeLogic).AddPreLogic(internalKnowledgeBaseRecallMetaFetcher)
	stageKbRecall.AddLogics(
		kbZhihuRecall, kbArxivRecall, kbReplenishArxivRecall, bgeEmbeddingFetcherLogic, bgeM3EmbeddingFetcherLogic, kbZhWikiRumRecall, kbEnWikiRumRecall,
		quKeywordFetcherLogic, kbZhWikiRuceneRecall, kbEnWikiRuceneRecall, personalKnowledgeBaseRumRecall, personalKnowledgeBaseRuceneRecall,
		specifiedDocRecall, specificRecallOverwriteConfig, kbRecallZhihuSourceMerge, personalKnowledgeBaseMergeLogic, kbRecallFinalSourceMerge,
		internalKnowledgeBaseRumRecall, internalKnowledgeBaseRuceneRecall)

	var recallMergeStage = zagHandler.NewZagStageDeclare(conf.RecallMergeLogic).AddPres(stageKbRecall)
	var recallMerge = zagHandler.NewZagLogicDeclare(conf.RecallMergeLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(contentCoreMetaFetcher)
	recallMergeStage.AddLogics(recallMerge)

	var agentJudgeStage2 = zagHandler.NewZagStageDeclare(conf.AgentJudgeStage2).AddPres(recallMergeStage)
	var agentOverwriteConfig2 = zagHandler.NewZagLogicDeclare(conf.AgentOverwriteConfigLogic2).SetClass(mapping.OverwriteConfigLogic{})
	agentJudgeStage2.AddLogics(agentOverwriteConfig2)

	//------- 管控过滤 filter---------
	var recallFilterStage = zagHandler.NewZagStageDeclare(conf.RecallFilterStage).AddPres(agentJudgeStage2)
	var recallInitFilter = zagHandler.NewZagLogicDeclare(conf.RecallInitFilterLogic).SetClass(frameworkFilter.InitFilterLogic[any, any, any]{})
	// 内容管控过滤
	var validContentRegulateFetcherLogic = zagHandler.NewZagLogicDeclare(conf.ValidContentRegulateFetcherLogic).SetClass(meta_fetcher.ContentRegulateLogic{}).
		AddPreLogic(recallInitFilter)
	var contentRegulateFilterLogic = zagHandler.NewZagLogicDeclare(conf.ContentRegulateFilterLogic).SetClass(filter.ContentRegulateFilterLogic{}).
		AddPreLogic(validContentRegulateFetcherLogic)
	// 内容为空过滤
	var emptyMetaFilter = zagHandler.NewZagLogicDeclare(conf.EmptyContentFilterLogic).SetClass(filter.EmptyMetaFilterLogic{}).
		AddPreLogic(recallInitFilter)
	// 内容安全过滤
	var recallSecurityValidContentFetcher = zagHandler.NewZagLogicDeclare(conf.RecallSecurityValidContentFetcherLogic).SetClass(security.SecurityReviewRecallLogic{}).
		AddPreLogic(recallInitFilter)
	var recallSecurityContentFilter = zagHandler.NewZagLogicDeclare(conf.RecallSecurityContentFilterLogic).SetClass(filter.KbRecallSecurityFilterLogic{}).
		AddPreLogic(recallSecurityValidContentFetcher)
	// 内容质量过滤
	var tagCoreFetcherLogic = zagHandler.NewZagLogicDeclare(conf.TagCoreMetaFetcherLogic).SetClass(meta_fetcher.TagCoreMetaFetcherLogic{}).AddPreLogic(recallInitFilter)
	var tagCoreFilterLogic = zagHandler.NewZagLogicDeclare(conf.KbRecallTagFilterLogic).SetClass(filter.KbRecallTagFilterLogic{}).AddPreLogic(tagCoreFetcherLogic)
	// 内容相似度过滤
	var recallSimHashFilter = zagHandler.NewZagLogicDeclare(conf.KbRecallSimhashFilterLogic).SetClass(filter.KbRecallSimHashFilterLogic{}).
		AddPreLogic(recallInitFilter)
	var recallPostFilter = zagHandler.NewZagLogicDeclare(conf.RecallPostFilterLogic).SetClass(frameworkFilter.FilterPostLogic[any, any, any]{}).
		AddPreLogic(emptyMetaFilter).AddPreLogic(recallSecurityContentFilter).AddPreLogic(contentRegulateFilterLogic).AddPreLogic(tagCoreFilterLogic).AddPreLogic(recallSimHashFilter)
	recallFilterStage.AddLogics(recallInitFilter, emptyMetaFilter,
		recallSecurityValidContentFetcher, recallSecurityContentFilter, validContentRegulateFetcherLogic, contentRegulateFilterLogic,
		tagCoreFetcherLogic, tagCoreFilterLogic, recallSimHashFilter, recallPostFilter)

	// Recall To Model ReRank
	var recall2ModelReRankStage = zagHandler.NewZagStageDeclare(conf.Recall2ModelReRankStage).AddPres(recallFilterStage)
	var kbRecallChunkCite = zagHandler.NewZagLogicDeclare(conf.KbRecallChunkCiteLogic).SetClass(rerank.KbRecallChunkCiteBeforeLogic{})
	// 发送Recall 结果到 chan
	var uploadRecallChanStage = zagHandler.NewZagStageDeclare(conf.UploadRecallChanStage)
	var uploadRecallChan = zagHandler.NewZagLogicDeclare(conf.UploadRecallChanLogic).SetClass(response.UploadRespChanLogic{}).AddPreLogic(kbRecallChunkCite)
	uploadRecallChanStage.AddLogics(uploadRecallChan)
	// 分chunk和评分(新)
	var recall2ModelChunkAndScore = zagHandler.NewZagLogicDeclare(conf.Recall2ModelChunkAndScoreLogic).
		SetClass(rerank.KbRecallChunkAndScoreLogic{}).AddPreLogic(uploadRecallChan)
	var recall2ModelAfterReRank = zagHandler.NewZagLogicDeclare(conf.Recall2ModelReRankLogic).
		SetClass(retrieval.KbRecallChunkAndReRankAfterLogic{}).SetStore(conf2.RecallCardLogicStoreKey.String()).AddPreLogic(recall2ModelChunkAndScore)
	recall2ModelReRankStage.AddLogics(kbRecallChunkCite, recall2ModelChunkAndScore, recall2ModelAfterReRank)

	//------answer 生成阶段--------
	var stageGenerate = zagHandler.NewZagStageDeclare(conf.GenerateStage).AddPres(recall2ModelReRankStage)
	var streamChatLogic = zagHandler.NewZagLogicDeclare(conf.StreamChatLogic).SetClass(generate.StreamChatLogic{}).
		SetTimeOut(300 * 1000)
	var chatLogic = zagHandler.NewZagLogicDeclare(conf.ChatLogic).SetClass(generate.ChatLogic{}).SetTimeOut(300 * 1000)
	stageGenerate.AddLogics(streamChatLogic, chatLogic)

	//------answer 安全审核--------
	var answerSecurityStage = zagHandler.NewZagStageDeclare(conf.AnswerSecurityStage)
	var answerSecurityPostBeforeLogic = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityBeforePostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(streamChatLogic).SetStore(conf2.StreamChatResultStoreKey.String())
	var securityReviewOut = zagHandler.NewZagLogicDeclare(conf.SecurityReviewOutLogic).SetClass(security.SecurityReviewLogic{}).
		AddPreLogic(answerSecurityPostBeforeLogic)
	var answerSecurityBeforeUnPass = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityBeforeUnPassLogic).
		SetClass(empty.EmptyLogic{}).AddPreLogic(answerSecurityPostBeforeLogic)
	var answerSecurityMerge = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityMergeLogic).SetClass(empty.EmptyLogic{}).
		AddPreLogic(securityReviewOut).AddPreLogic(answerSecurityBeforeUnPass)
	answerSecurityStage.AddLogics(answerSecurityPostBeforeLogic, securityReviewOut, answerSecurityBeforeUnPass, answerSecurityMerge)

	//------word 安全审核--------
	var wordSecurityStage = zagHandler.NewZagStageDeclare(conf.WordSecurityStage)
	var chatAnswer2SentenceLogic = zagHandler.NewZagLogicDeclare(conf.Answer2SentenceLogic).SetClass(mapping.ChatAnswer2SentenceLogic{}).AddPreLogic(chatLogic)
	var wordSecurityReviewLogic = zagHandler.NewZagLogicDeclare(conf.RelevantQuerySecurityReviewLogic).SetClass(security.SecurityReviewWordLogic{}).
		AddPreLogic(chatAnswer2SentenceLogic)
	wordSecurityStage.AddLogics(chatAnswer2SentenceLogic, wordSecurityReviewLogic)

	//------resp 安全审核--------
	var respSecurityStage = zagHandler.NewZagStageDeclare(conf.RespSecurityStage).AddPres(answerSecurityStage, wordSecurityStage)
	var respSecurityPostLogic = zagHandler.NewZagLogicDeclare(conf.RespSecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).SetStore(conf2.StreamChatResultStoreKey.String())
	var uploadRespChanLogic = zagHandler.NewZagLogicDeclare(conf.UploadQueryChanLogic).SetClass(response.UploadRespChanLogic{}).
		AddPreLogic(respSecurityPostLogic)
	respSecurityStage.AddLogics(respSecurityPostLogic, uploadRespChanLogic)

	//------响应阶段--------
	var stageResponse = zagHandler.NewZagStageDeclare(conf.ResponseStage).AddPres(emptyStage, queryAndQueryMergeSafetyUnPassedStage, respSecurityStage)
	var BuildResponse = zagHandler.NewZagLogicDeclare(conf.ResponseLogic).SetClass(response.BuildResponseLogic{})

	var saveDialog = zagHandler.NewZagLogicDeclare(conf.SaveDialogLogic).SetClass(consumer.SaveDialogRecordLogic{}).AddPreLogic(BuildResponse)
	var tracingRecordLogic = zagHandler.NewZagLogicDeclare(conf.TracingRecordLogic).SetClass(finalizer.TracingRecordLogic{}).AddPreLogic(BuildResponse)
	var saveQueryResultLogic = zagHandler.NewZagLogicDeclare(conf.SaveQueryResultLogic).SetClass(finalizer.SaveQueryResultLogic{}).AddPreLogic(BuildResponse)
	stageResponse.AddLogics(BuildResponse, saveDialog, tracingRecordLogic, saveQueryResultLogic)

	requestLegalityChooseLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {queryMerge.Name, securityReview.Name, redLine.Name, faq.Name},
		entities.Break:  {illegalRequest.Name},
	})
	docRouterJudge.SetSelectEdge(map[string][]string{
		entities.KnowledgeBase.String():   {queryRoute.Name},
		entities.SpecifiedDocAny.String(): {specifiedDocRecall.Name},
	})

	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {queryAndQueryMergeSafetyJudge.Name},
		entities.Break:  {queryAndQueryMergeSafetyJudge.Name},
	})
	securityPostM.SetSelectEdge(map[string][]string{
		entities.Normal: {queryAndQueryMergeSafetyJudge.Name},
		entities.Break:  {queryAndQueryMergeSafetyJudge.Name},
	})
	queryAndQueryMergeSafetyJudge.SetSelectEdge(map[string][]string{
		entities.Normal: {docRouterJudge.Name},
		entities.Break:  {queryAndQueryMergeSafetyUnPassed.Name},
	})

	answerSecurityPostBeforeLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {securityReviewOut.Name},
		entities.Break:  {answerSecurityBeforeUnPass.Name},
	})

	respSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {uploadRespChanLogic.Name},
		entities.Break:  {uploadRespChanLogic.Name},
	})

	stages := []*zagHandler.DeclareStage{
		stageRoot, stagePrepare, emptyStage, emptyPrepareStage, securityStage, stageQueryMerge, agentJudgeStage,
		securityStageM, queryAndQueryMergeSafetyUnPassedStage, docRouterJudgeStage, agentJudgeStage2,
		stageKbRecall, queryAndQueryMergeSafetyJudgeStage, recallMetaFetcherStage, recallFilterStage, recall2ModelReRankStage,
		uploadRecallChanStage, stageGenerate, answerSecurityStage, wordSecurityStage, respSecurityStage, stageResponse, requestLegalityStage, recallMergeStage,
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
