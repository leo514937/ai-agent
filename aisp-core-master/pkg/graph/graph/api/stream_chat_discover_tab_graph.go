package api

import (
	bizAnswer "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/extra_answer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/finalizer"
	ai_tab_rerank "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/prepare"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/resources"
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

// StreamChatDiscoverTabGraph 发现Tab
func StreamChatDiscoverTabGraph[C, U, I any](bizType string) *graph.Graph {
	//========图声明========
	var apiConfigPath = zagHandler.GetApiConfigPath()
	var zagGraph = zagHandler.NewZagGraphDeclareWithInfo("chat_graph", entities.BuildGraphScene(graph_constant.ApiStreamChat, bizType), "1.54", "zhoupengcheng,wanghao11,wangran,keyan01", "发现tab图", apiConfigPath)
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
	// sessionInfo
	var sessionInfo = zagHandler.NewZagLogicDeclare(conf.SessionInfoLogic).SetClass(root.SessionInfoLogic{}).AddPreLogic(loadApolloConfig)
	// 用户标签
	var memberTagCore = zagHandler.NewZagLogicDeclare(conf.MemberTagCoreLogic).SetClass(root.MemberTagCoreV2Logic{}).AddPreLogic(loadApolloConfig)
	// config 参数
	var requestConfig = zagHandler.NewZagLogicDeclare(conf.RequestConfigLogic).SetClass(prepare.RequestConfigLogic{}).AddPreLogic(memberTagCore)
	// 历史记录
	var chatHistory = zagHandler.NewZagLogicDeclare(conf.ChatHistoryLogic).SetClass(root.ChatHistoryLogic{}).AddPreLogic(requestConfig)
	// 名词解释
	var queryDefinition = zagHandler.NewZagLogicDeclare(conf.QueryDefinitionLogic).SetClass(prepare.QueryDefinitionLogic{}).AddPreLogic(requestConfig)
	stagePrepare.AddLogics(sessionInfo, requestConfig, chatHistory, memberTagCore, queryDefinition, loadApolloConfig)

	//------prepare阶段后空算子 保障流程图可以编排使用--------
	var emptyPrepareStage = zagHandler.NewZagStageDeclare(conf.EmptyPrepareStageLogic).AddPres(stageRoot)
	var emptyPrepare = zagHandler.NewZagLogicDeclare(conf.EmptyPrepareLogic).SetClass(empty.EmptyLogic{})
	emptyPrepareStage.AddLogics(emptyPrepare)

	//------cache--------
	var cacheStage = zagHandler.NewZagStageDeclare(conf.CacheStage).AddPres(stagePrepare, emptyPrepareStage)
	var chatCacheChoose = zagHandler.NewZagLogicDeclare(conf.ChatCacheChooseLogic).SetClass(chat_cache.ChatCacheChooseLogic{})
	cacheStage.AddLogics(chatCacheChoose)

	//------请求参数合法校验------
	var requestLegalityStage = zagHandler.NewZagStageDeclare(conf.RequestLegalityStage).AddPres(cacheStage)
	var requestLegalityChooseLogic = zagHandler.NewZagLogicDeclare(conf.RequestLegalityLogic).SetClass(choose2.RequestLegalityVerifyLogic{})
	requestLegalityStage.AddLogics(requestLegalityChooseLogic)

	//------HitCache--------
	var emptyStage = zagHandler.NewZagStageDeclare(conf.EmptyStage)
	var hitCache = zagHandler.NewZagLogicDeclare(conf.HitCacheLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(chatCacheChoose)
	var illegalRequest = zagHandler.NewZagLogicDeclare(conf.IllegalRequestLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(requestLegalityChooseLogic)
	emptyStage.AddLogics(hitCache, illegalRequest)

	// ------agent选择----------
	var agentJudgeStage = zagHandler.NewZagStageDeclare(conf.AgentJudgeStage).AddPres(requestLegalityStage)
	var queryRoute = zagHandler.NewZagLogicDeclare(conf.QueryRouterLogic).SetClass(meta_fetcher.QueryRouterLogic{})
	var agentOverwriteConfig = zagHandler.NewZagLogicDeclare(conf.AgentOverwriteConfigLogic).SetClass(mapping.OverwriteConfigLogic{}).AddPreLogic(queryRoute)
	agentJudgeStage.AddLogics(queryRoute, agentOverwriteConfig)

	//------安全模块--------
	var securityStage = zagHandler.NewZagStageDeclare(conf.SecurityStage).AddPres(agentJudgeStage)
	var redLine = zagHandler.NewZagLogicDeclare(conf.RedLineLogic).SetClass(security.RedLineLogic{})

	var securityReview = zagHandler.NewZagLogicDeclare(conf.SecurityReviewLogic).SetClass(security.SecurityReviewLogic{})
	var faq = zagHandler.NewZagLogicDeclare(conf.FaqLogic).SetClass(security.FAQLogic{})

	var securityPost = zagHandler.NewZagLogicDeclare(conf.SecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(redLine).AddPreLogic(securityReview).AddPreLogic(faq)

	securityStage.AddLogics(redLine, securityReview, faq, securityPost)

	//------相关追问跳转导流，加强相关性--------
	// 拆解 docId docType 伪造为 知乎召回内容
	var extraAnswerDisassemblyInfoStage = zagHandler.NewZagStageDeclare(conf.ExtraAnswerDisassemblyInfoStage).AddPres(agentJudgeStage)
	var extraAnswerCovertLogic = zagHandler.NewZagLogicDeclare(conf.ExtraAnswerCovertLogic).SetClass(bizAnswer.ExtraAnswerContentCovertLogic{})
	extraAnswerDisassemblyInfoStage.AddLogics(extraAnswerCovertLogic)

	//------QueryMerge阶段--------
	var stageQueryMerge = zagHandler.NewZagStageDeclare(conf.QueryMergeStage).AddPres(extraAnswerDisassemblyInfoStage)
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

	//------- query merge MetaFetcher---------
	var queryMergeMetaFetcherStage = zagHandler.NewZagStageDeclare(conf.QueryMergeMetaFetcherStage).AddPres(stageQueryMerge)
	var quKeywordFetcherLogic = zagHandler.NewZagLogicDeclare(conf.QuKeywordFetcherLogic).SetClass(meta_fetcher.QuKeywordFetcherLogic{})
	var bgeEmbeddingFetcherLogic = zagHandler.NewZagLogicDeclare(conf.BgeEmbeddingFetcherLogic).SetClass(meta_fetcher.KlaraEmbeddingFetcherLogic{})
	queryMergeMetaFetcherStage.AddLogics(quKeywordFetcherLogic, bgeEmbeddingFetcherLogic)

	//------recall阶段--------
	var stageKbRecall = zagHandler.NewZagStageDeclare(conf.KbRecallStage).AddPres(stageQueryMerge)

	// 站内召回
	var kbZhihuRecall = zagHandler.NewZagLogicDeclare(conf.KbZhihuRecallLogic).SetClass(recall.KbZhihuRecallLogic{})
	// 站内同问题下其他回答扩充
	var kbZhihuSameQuestionAnswerRecall = zagHandler.NewZagLogicDeclare(conf.KbSameQuestionAnswerAppendLogic).SetClass(recall.KbSameQuestionAnswerAppendLogic{}).AddPreLogic(kbZhihuRecall)

	// Bing 召回
	var kbBingRecall = zagHandler.NewZagLogicDeclare(conf.KbBingRecallLogic).SetClass(recall.KbOutSiteRecallLogic{})

	// 搜狗 召回
	var kbSougouRecall = zagHandler.NewZagLogicDeclare(conf.KbSougouRecallLogic).SetClass(recall.KbOutSiteRecallLogic{})

	// 夸克 召回
	var kbQuarkRecall = zagHandler.NewZagLogicDeclare(conf.KbQuarkRecallLogic).SetClass(recall.KbOutSiteRecallLogic{})

	// Serper 召回
	var kbSerperRecall = zagHandler.NewZagLogicDeclare(conf.KbSerperRecallLogic).SetClass(recall.KbOutSiteRecallLogic{})

	// 知+汽车 召回
	var zplusAutomotiveRecall = zagHandler.NewZagLogicDeclare(conf.KbZPlusAutomotiveRecallLogic).SetClass(recall.ZplusRecallLogic{})

	// 知乎站内内容 metaFetcher，为了 recallMerge 时计算相似度分数用标题 + 正文
	var kbZhihuRecallMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbZhihuRecallMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).AddPreLogic(kbZhihuSameQuestionAnswerRecall)

	// 站外自建索引 rucene 召回
	var outSiteRuceneRecallLogic = zagHandler.NewZagLogicDeclare(conf.KbOutSiteRuceneRecallLogic).SetClass(recall.RuceneLogic{}).AddPreLogic(quKeywordFetcherLogic)
	var outSiteRumRecallLogic = zagHandler.NewZagLogicDeclare(conf.KbOutSiteRumRecallLogic).SetClass(recall.RumRecallLogic{}).AddPreLogic(bgeEmbeddingFetcherLogic)
	var kbRecallOutSiteSourceMerge = zagHandler.NewZagLogicDeclare(conf.KbRecallOutSiteSourceMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(outSiteRuceneRecallLogic).AddPreLogic(outSiteRumRecallLogic)
	var kbRecallZhihuSourceMerge = zagHandler.NewZagLogicDeclare(conf.KbRecallZhihuSourceMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(kbZhihuRecallMetaFetcher)

	// 创作者召回
	var authorRecallLogic = zagHandler.NewZagLogicDeclare(conf.AuthorSearchRecallLogic).SetClass(recall.RumRecallLogic{}).AddPreLogic(bgeEmbeddingFetcherLogic)
	var authorSelfRecallLogic = zagHandler.NewZagLogicDeclare(conf.AuthorSearchSelfRecallLogic).SetClass(recall.ForwardIndexRecallLogic{})

	var authorSearchMergeLogic = zagHandler.NewZagLogicDeclare(conf.AuthorSearchMergeLogic).SetClass(ai_tab_rerank.AuthorMergeLogic{}).AddPreLogic(authorRecallLogic).AddPreLogic(authorSelfRecallLogic)
	stageKbRecall.AddLogics(kbZhihuRecall, kbZhihuSameQuestionAnswerRecall, kbBingRecall, kbSougouRecall, kbQuarkRecall, kbSerperRecall, zplusAutomotiveRecall, outSiteRuceneRecallLogic, outSiteRumRecallLogic, authorRecallLogic,
		authorSelfRecallLogic, kbZhihuRecallMetaFetcher, kbRecallOutSiteSourceMerge, kbRecallZhihuSourceMerge, authorSearchMergeLogic)

	//------recall 阶段（知识库增强召回）--------
	// 合并召回源
	var recallMergeStage = zagHandler.NewZagStageDeclare(conf.RecallMergeStage).AddPres(stageKbRecall)
	var kbRecallSourceMerge = zagHandler.NewZagLogicDeclare(conf.KbRecallSourceMergeLogic).SetClass(merge.KbRecallSourceMergeLogic{})
	recallMergeStage.AddLogics(kbRecallSourceMerge)

	var agentJudgeStage2 = zagHandler.NewZagStageDeclare(conf.AgentJudgeStage2).AddPres(recallMergeStage)
	var agentOverwriteConfig2 = zagHandler.NewZagLogicDeclare(conf.AgentOverwriteConfigLogic2).SetClass(mapping.OverwriteConfigLogic{})
	agentJudgeStage2.AddLogics(agentOverwriteConfig2)

	//------- recall MetaFetcher---------
	var recallMetaFetcherStage = zagHandler.NewZagStageDeclare(conf.RecallMetaFetcherStage).AddPres(agentJudgeStage2)
	// 自身 meta fetchefr
	var kbRecallMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{})
	// 创作者标签 fetcher
	var authorTagFetcherLogic = zagHandler.NewZagLogicDeclare(conf.AuthorTagFetcherLogic).SetClass(meta_fetcher.AuthorTagCoreMetaFetcherLogic{}).AddPreLogic(kbRecallMetaFetcher)
	// 父节点 meta fetcher，回答获取问题的 contentInfo
	var kbRecallParentMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallParentMetaFetcherLogic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).AddPreLogic(kbRecallMetaFetcher)
	// 子节点 meta fetcher，问题获取其下 top1 个回答的 contentInfo
	var kbRecallChildMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallChildMetaFetcherLogic).SetClass(meta_fetcher.ChildContentCoreMetaFetcherLogic{}).AddPreLogic(kbRecallMetaFetcher)
	// 结果合并，问题映射成回答
	var kbRecallQuestion2AnswerLogic = zagHandler.NewZagLogicDeclare(conf.KbRecallQuestion2AnswerLogic).SetClass(mapping.Question2AnswerLogic{}).AddPreLogic(kbRecallParentMetaFetcher).AddPreLogic(kbRecallChildMetaFetcher)
	recallMetaFetcherStage.AddLogics(kbRecallMetaFetcher, authorTagFetcherLogic, kbRecallParentMetaFetcher, kbRecallChildMetaFetcher, kbRecallQuestion2AnswerLogic)

	// 过滤内外部召回
	var recallIoFilterStage = zagHandler.NewZagStageDeclare(conf.RecallIoFilterStage).AddPres(recallMetaFetcherStage)
	// 内部召回过滤
	var recallInsideFilter = zagHandler.NewZagLogicDeclare(conf.RecallInsideFilterLogic).SetClass(filter.KbRecallIoFilterLogic{})
	// 外部召回过滤 drop
	var recallOutsideFilter = zagHandler.NewZagLogicDeclare(conf.RecallOutsideFilterLogic).SetClass(filter.KbRecallIoFilterLogic{})
	recallIoFilterStage.AddLogics(recallInsideFilter, recallOutsideFilter)

	//------- 站内内容管控过滤 filter---------
	var onSiteFilterStage = zagHandler.NewZagStageDeclare(conf.OnSiteStageFilterStage)
	var onSiteInitFilter = zagHandler.NewZagLogicDeclare(conf.OnSiteInitFilterLogic).SetClass(frameworkFilter.InitFilterLogic[any, any, any]{}).
		AddPreLogic(recallInsideFilter)
	var validContentRegulateFetcherLogic = zagHandler.NewZagLogicDeclare(conf.ValidContentRegulateFetcherLogic).SetClass(meta_fetcher.ContentRegulateLogic{}).
		AddPreLogic(onSiteInitFilter)
	var contentRegulateFilterLogic = zagHandler.NewZagLogicDeclare(conf.ContentRegulateFilterLogic).SetClass(filter.ContentRegulateFilterLogic{}).
		AddPreLogic(validContentRegulateFetcherLogic)

	//------- 站内内容低质过滤 filter ---------
	var tagCoreFetcherLogic = zagHandler.NewZagLogicDeclare(conf.TagCoreMetaFetcherLogic).SetClass(meta_fetcher.TagCoreMetaFetcherLogic{}).AddPreLogic(onSiteInitFilter)
	var tagCoreFilterLogic = zagHandler.NewZagLogicDeclare(conf.KbRecallTagFilterLogic).SetClass(filter.KbRecallTagFilterLogic{}).AddPreLogic(tagCoreFetcherLogic)

	var emptyMetaFilterLogic = zagHandler.NewZagLogicDeclare(conf.EmptyMetaFilterLogic).SetClass(filter.EmptyMetaFilterLogic{}).
		AddPreLogic(onSiteInitFilter)
	var onSitePostFilter = zagHandler.NewZagLogicDeclare(conf.OnSitePostFilterLogic).SetClass(frameworkFilter.FilterPostLogic[any, any, any]{}).
		AddPreLogic(contentRegulateFilterLogic).AddPreLogic(emptyMetaFilterLogic).AddPreLogic(tagCoreFilterLogic)
	onSiteFilterStage.AddLogics(onSiteInitFilter, validContentRegulateFetcherLogic, contentRegulateFilterLogic, onSitePostFilter, emptyMetaFilterLogic, tagCoreFetcherLogic, tagCoreFilterLogic)

	//------- 站外内容安全过滤 filter---------
	var outSiteFilterStage = zagHandler.NewZagStageDeclare(conf.OutSiteStageFilterStage)
	var outSiteInitFilter = zagHandler.NewZagLogicDeclare(conf.OutSiteInitFilterLogic).SetClass(frameworkFilter.InitFilterLogic[any, any, any]{}).
		AddPreLogic(recallOutsideFilter)
	var validContentSecurityFetcherLogic = zagHandler.NewZagLogicDeclare(conf.ValidContentSecurityFetcherLogic).SetClass(security.SecurityReviewRecallLogic{}).
		AddPreLogic(outSiteInitFilter)
	var contentSecurityFilterLogic = zagHandler.NewZagLogicDeclare(conf.ContentSecurityFilterLogic).SetClass(filter.KbRecallSecurityFilterLogic{}).
		AddPreLogic(validContentSecurityFetcherLogic)
	var outSitePostFilter = zagHandler.NewZagLogicDeclare(conf.OutSitePostFilterLogic).SetClass(frameworkFilter.FilterPostLogic[any, any, any]{}).
		AddPreLogic(contentSecurityFilterLogic)
	outSiteFilterStage.AddLogics(outSiteInitFilter, validContentSecurityFetcherLogic, contentSecurityFilterLogic, outSitePostFilter)

	//------- 站外内容安全过滤 filter---------
	var finalFilterStage = zagHandler.NewZagStageDeclare(conf.FinalStageFilterStage)
	var finalInitMerge = zagHandler.NewZagLogicDeclare(conf.FinalInitMergeFilterLogic).SetClass(empty.EmptyLogic{}).
		AddPreLogic(onSitePostFilter).AddPreLogic(outSitePostFilter)
	var finalInitFilter = zagHandler.NewZagLogicDeclare(conf.FinalInitFilterLogic).SetClass(frameworkFilter.InitFilterLogic[any, any, any]{}).
		AddPreLogic(finalInitMerge)
	// --- 所有内容基于 simhash 去重
	var recallSimHashFilter = zagHandler.NewZagLogicDeclare(conf.KbRecallSimhashFilterLogic).SetClass(filter.KbRecallSimHashFilterLogic{}).
		AddPreLogic(finalInitFilter)
	var finalPostFilter = zagHandler.NewZagLogicDeclare(conf.FinalPostFilterLogic).SetClass(frameworkFilter.FilterPostLogic[any, any, any]{}).
		AddPreLogic(recallSimHashFilter)
	finalFilterStage.AddLogics(finalInitMerge, finalInitFilter, recallSimHashFilter, finalPostFilter)

	//------recall handle 阶段--------
	var kbRecallHandleStage = zagHandler.NewZagStageDeclare(conf.KbRecallHandleStage).AddPres(recallMetaFetcherStage)
	var kbRecallChunkAndReRankV2BeforeLogic = zagHandler.NewZagLogicDeclare(conf.KbRecallChunkAndReRankV2BeforeLogic).
		SetClass(rerank.KbRecallChunkAndReRankV2BeforeLogic{}).
		AddPreLogic(finalPostFilter)
	kbRecallHandleStage.AddLogics(kbRecallChunkAndReRankV2BeforeLogic)

	//------召回安全模块--------
	var recallAndSafetyJudgeChooseStage = zagHandler.NewZagStageDeclare(conf.RecallAndSafetyJudgeChooseStage)
	var recallAndSafetyJudgeChoose = zagHandler.NewZagLogicDeclare(conf.RecallAndSafetyJudgeChooseLogic).
		SetClass(security_post.RecallAndSafetyJudgeChoose{}).AddPreLogic(securityPost).AddPreLogic(securityPostM).AddPreLogic(kbRecallChunkAndReRankV2BeforeLogic)
	recallAndSafetyJudgeChooseStage.AddLogics(recallAndSafetyJudgeChoose)

	//------空算子(安全未通过)--------
	var recallAndSafetyUnPassedStage = zagHandler.NewZagStageDeclare(conf.RecallAndSafetyUnPassedStage)
	var recallAndSafetyUnPassedLogic = zagHandler.NewZagLogicDeclare(conf.RecallAndSafetyUnPassedLogic).
		SetClass(empty.EmptyLogic{}).AddPreLogic(recallAndSafetyJudgeChoose)
	recallAndSafetyUnPassedStage.AddLogics(recallAndSafetyUnPassedLogic)

	// 发送Recall 结果到 chan
	var uploadRecallChanStage = zagHandler.NewZagStageDeclare(conf.UploadRecallChanStage)
	var uploadRecallChan = zagHandler.NewZagLogicDeclare(conf.UploadRecallChanLogic).SetClass(response.UploadRespChanLogic{}).SetStore(conf2.RecallCardLogicStoreKey.String()).
		AddPreLogic(recallAndSafetyJudgeChoose)
	uploadRecallChanStage.AddLogics(uploadRecallChan)

	var uploadRecallChanThenBreakStage = zagHandler.NewZagStageDeclare(conf.UploadRecallChanThenBreakStage)
	var uploadRecallChanThenBreak = zagHandler.NewZagLogicDeclare(conf.UploadRecallChanThenBreakLogic).SetClass(response.UploadRespChanLogic{}).
		AddPreLogic(recallAndSafetyJudgeChoose)
	uploadRecallChanThenBreakStage.AddLogics(uploadRecallChanThenBreak)

	// Recall To Model ReRank
	var recall2ModelReRankStage = zagHandler.NewZagStageDeclare(conf.Recall2ModelReRankStage).AddPres(uploadRecallChanStage)
	// 分chunk和评分(新)
	var recall2ModelChunkAndScore = zagHandler.NewZagLogicDeclare(conf.Recall2ModelChunkAndScoreLogic).
		SetClass(rerank.KbRecallChunkAndScoreLogic{})
	var recall2ModelAfterReRank = zagHandler.NewZagLogicDeclare(conf.Recall2ModelReRankLogic).
		SetClass(rerank.KbRecallChunkAndReRankV2AfterLogic{}).AddPreLogic(recall2ModelChunkAndScore)
	recall2ModelReRankStage.AddLogics(recall2ModelChunkAndScore, recall2ModelAfterReRank)

	//------answer 生成阶段--------
	var stageGenerate = zagHandler.NewZagStageDeclare(conf.GenerateStage).AddPres(recall2ModelReRankStage)
	var streamChatLogic = zagHandler.NewZagLogicDeclare(conf.StreamChatLogic).SetClass(generate.StreamChatLogic{}).
		SetTimeOut(300 * 1000)
	var chatLogic = zagHandler.NewZagLogicDeclare(conf.ChatLogic).SetClass(generate.ChatLogic{}).SetTimeOut(300 * 1000)
	stageGenerate.AddLogics(streamChatLogic, chatLogic)

	//------answer 安全审核--------
	var answerSecurityStage = zagHandler.NewZagStageDeclare(conf.AnswerSecurityStage)
	var answerSecurityPostBefore = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityBeforePostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(streamChatLogic).SetStore(conf2.StreamChatResultStoreKey.String())
	var securityReviewOut = zagHandler.NewZagLogicDeclare(conf.SecurityReviewOutLogic).SetClass(security.SecurityReviewLogic{}).
		AddPreLogic(answerSecurityPostBefore)
	var answerSecurityBeforeUnPass = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityBeforeUnPassLogic).SetClass(empty.EmptyLogic{}).
		AddPreLogic(answerSecurityPostBefore)
	var answerSecurityMerge = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityMergeLogic).SetClass(empty.EmptyLogic{}).
		AddPreLogic(securityReviewOut).AddPreLogic(answerSecurityBeforeUnPass)
	answerSecurityStage.AddLogics(answerSecurityPostBefore, securityReviewOut, answerSecurityBeforeUnPass, answerSecurityMerge)

	//------word 安全审核--------
	var wordSecurityStage = zagHandler.NewZagStageDeclare(conf.WordSecurityStage)
	var chatAnswer2SentenceLogic = zagHandler.NewZagLogicDeclare(conf.Answer2SentenceLogic).SetClass(mapping.ChatAnswer2SentenceLogic{}).
		AddPreLogic(chatLogic)
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
	var stageResponse = zagHandler.NewZagStageDeclare(conf.ResponseStage).AddPres(emptyStage, recallAndSafetyUnPassedStage, uploadRecallChanThenBreakStage, respSecurityStage)
	var buildResponse = zagHandler.NewZagLogicDeclare(conf.ResponseLogic).SetClass(response.BuildResponseLogic{})
	var SaveDialog = zagHandler.NewZagLogicDeclare(conf.SaveDialogLogic).SetClass(consumer.SaveDialogRecordLogic{}).AddPreLogic(buildResponse)
	var tracingRecordLogic = zagHandler.NewZagLogicDeclare(conf.TracingRecordLogic).SetClass(finalizer.TracingRecordLogic{}).AddPreLogic(buildResponse)
	var saveQueryResultLogic = zagHandler.NewZagLogicDeclare(conf.SaveQueryResultLogic).SetClass(finalizer.SaveQueryResultLogic{}).AddPreLogic(buildResponse)
	var lastNRecordLogic = zagHandler.NewZagLogicDeclare(conf.LastNRecordLogic).SetClass(finalizer.LastNRecordLogic{}).AddPreLogic(buildResponse)
	stageResponse.AddLogics(buildResponse, SaveDialog, tracingRecordLogic, saveQueryResultLogic, lastNRecordLogic)

	chatCacheChoose.SetSelectEdge(map[string][]string{
		entities.HitCache:  {hitCache.Name},
		entities.MissCache: {requestLegalityChooseLogic.Name},
	})
	requestLegalityChooseLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {queryRoute.Name},
		entities.Break:  {illegalRequest.Name},
	})

	recallAndSafetyJudgeChoose.SetSelectEdge(map[string][]string{
		entities.Normal:                {uploadRecallChan.Name},
		entities.Break:                 {recallAndSafetyUnPassedLogic.Name},
		entities.UploadRecallThenBreak: {uploadRecallChanThenBreak.Name},
	})
	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {recallAndSafetyJudgeChoose.Name},
		entities.Break:  {recallAndSafetyJudgeChoose.Name},
	})
	securityPostM.SetSelectEdge(map[string][]string{
		entities.Normal: {recallAndSafetyJudgeChoose.Name},
		entities.Break:  {recallAndSafetyJudgeChoose.Name},
	})
	answerSecurityPostBefore.SetSelectEdge(map[string][]string{
		entities.Normal: {securityReviewOut.Name},
		entities.Break:  {answerSecurityBeforeUnPass.Name},
	})
	respSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {uploadRespChanLogic.Name},
		entities.Break:  {uploadRespChanLogic.Name},
	})

	stages := []*zagHandler.DeclareStage{
		stageRoot, stagePrepare, cacheStage, agentJudgeStage, emptyStage, emptyPrepareStage, securityStage, stageQueryMerge,
		securityStageM, recallAndSafetyUnPassedStage, recallMergeStage, agentJudgeStage2,
		stageKbRecall, recallAndSafetyJudgeChooseStage, recallMetaFetcherStage, recallIoFilterStage, queryMergeMetaFetcherStage,
		onSiteFilterStage, outSiteFilterStage, finalFilterStage, kbRecallHandleStage, uploadRecallChanStage, uploadRecallChanThenBreakStage,
		stageGenerate, answerSecurityStage, wordSecurityStage, respSecurityStage, stageResponse,
		recall2ModelReRankStage, requestLegalityStage, extraAnswerDisassemblyInfoStage,
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
