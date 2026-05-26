package api

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/finalizer"
	ai_tab_rerank "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/merge"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/resources"
	meta_fetcher2 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_pro/graph/logic/meta_fetcher"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/conf_stage"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/logic/retrieval"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/filter"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	frameworkFilter "git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// ZhiDaV2RecallGraph 直答 2.0 召回子图
func ZhiDaV2RecallGraph[C, U, I any](bizType string) *graph.Graph {
	//========图声明========
	var apiConfigPath = zagHandler.GetApiConfigPath()
	var zagGraph = zagHandler.NewZagGraphDeclareWithInfo("recall_graph", entities.BuildGraphScene(graph_constant.ApiRecall, bizType), "1.8", "zhoupengcheng,wanghao11,wangran,keyan01", "直答V2.0召回子图", apiConfigPath)

	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare(conf.RootStage)
	var userMessage = zagHandler.NewZagLogicDeclare(conf.UserMessageLogic).SetClass(root.RecallQueryLogic{})
	var recallConfigLogic = zagHandler.NewZagLogicDeclare(conf.RecallConfigLogic).SetClass(mapping.StageConfigLogic{}).AddPreLogic(userMessage)
	stageRoot.AddLogics(userMessage, recallConfigLogic)

	//------- query MetaFetcher---------
	var queryMetaFetcherStage = zagHandler.NewZagStageDeclare(conf.QueryMergeMetaFetcherStage).AddPres(stageRoot)
	var quKeywordFetcherLogic = zagHandler.NewZagLogicDeclare(conf.QuKeywordFetcherLogic).SetClass(meta_fetcher.QuKeywordFetcherLogic{})
	var bgeM3EmbeddingFetcherLogic = zagHandler.NewZagLogicDeclare(conf.BgeM3EmbeddingFetcherLogic).SetClass(meta_fetcher.KlaraEmbeddingFetcherLogic{})
	var bgeEmbeddingFetcherLogic = zagHandler.NewZagLogicDeclare(conf.BgeEmbeddingFetcherLogic).SetClass(meta_fetcher.KlaraEmbeddingFetcherLogic{})
	var queryMergeMetaFetcherEmpty = zagHandler.NewZagLogicDeclare(conf.QueryMergeFetcherEmptyLogic).
		SetClass(empty.EmptyLogic{}).AddPreLogic(quKeywordFetcherLogic).AddPreLogic(bgeM3EmbeddingFetcherLogic).AddPreLogic(bgeEmbeddingFetcherLogic)
	queryMetaFetcherStage.AddLogics(quKeywordFetcherLogic, bgeM3EmbeddingFetcherLogic, bgeEmbeddingFetcherLogic, queryMergeMetaFetcherEmpty)

	//------recall阶段--------
	var stageKbRecall = zagHandler.NewZagStageDeclare(conf.KbRecallStage).AddPres(queryMetaFetcherStage)
	// recall - 转换挂载 ========
	var mountDoc2SpecifiedDocRecall = zagHandler.NewZagLogicDeclare(conf.MountDoc2SpecifiedDocRecallLogic).SetClass(retrieval.MountDoc2SpecifiedDocRecallLogic{})
	var mountDoc2SpecifiedDocMetaFetcher = zagHandler.NewZagLogicDeclare(conf.MountDoc2SpecifiedDocMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).AddPreLogic(mountDoc2SpecifiedDocRecall)
	var mountDoc2SpecifiedDocInternalMetaFetcher = zagHandler.NewZagLogicDeclare(conf.MountDoc2SpecifiedDocInternalMetaFetcherLogic).SetClass(meta_fetcher2.InternalDocMetaFetcherLogic{}).AddPreLogic(mountDoc2SpecifiedDocRecall)
	var kbZhihuAuthorDocRecall = zagHandler.NewZagLogicDeclare(conf.KbZhihuAuthorDocRecallLogic).SetClass(recall.KbZhihuRecallLogic{})
	var KbZhihuAuthorDocSourceMerge = zagHandler.NewZagLogicDeclare(conf.KbZhihuAuthorDocSourceMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(kbZhihuAuthorDocRecall)
	// 论文召回 ========
	var kbPaperRecall = zagHandler.NewZagLogicDeclare(conf.KbPaperRecallLogic).SetClass(recall.KbZhihuRecallLogic{})
	var kbReplenishArxivRecall = zagHandler.NewZagLogicDeclare(conf.KbReplenishArxivRecallLogic).SetClass(recall.KbReplenishArxivRecallLogic{})
	var paperMetaFetcherMerge = zagHandler.NewZagLogicDeclare(conf.PaperMetaFetcherMergeLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(kbPaperRecall).AddPreLogic(kbReplenishArxivRecall)
	var paperMetaFetcher = zagHandler.NewZagLogicDeclare(conf.PaperMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).AddPreLogic(paperMetaFetcherMerge)
	var paperSourceMergeLogic = zagHandler.NewZagLogicDeclare(conf.KbRecallPaperSourceMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(paperMetaFetcher)
	// recall - 站外召回 ========
	var kbBingRecall = zagHandler.NewZagLogicDeclare(conf.KbBingRecallLogic).SetClass(recall.KbOutSiteRecallLogic{})
	var kbSerperRecall = zagHandler.NewZagLogicDeclare(conf.KbSerperRecallLogic).SetClass(recall.KbOutSiteRecallLogic{})
	var kbQuarkRecall = zagHandler.NewZagLogicDeclare(conf.KbQuarkRecallLogic).SetClass(recall.KbOutSiteRecallLogic{})
	var kbKexinRecall = zagHandler.NewZagLogicDeclare(conf.KbKexinRecallLogic).SetClass(recall.KbOutSiteRecallLogic{})
	// recall - 自建站外索引召回 ======
	var outSiteRuceneRecallLogic = zagHandler.NewZagLogicDeclare(conf.KbOutSiteRuceneRecallLogic).SetClass(recall.RuceneLogic{})
	var outSiteRumRecallLogic = zagHandler.NewZagLogicDeclare(conf.KbOutSiteRumRecallLogic).SetClass(recall.RumRecallLogic{})
	var kbRecallOutSiteSourceMerge = zagHandler.NewZagLogicDeclare(conf.KbRecallOutSiteSourceMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(outSiteRuceneRecallLogic).AddPreLogic(outSiteRumRecallLogic)
	var outSiteMetaFetcherMerge = zagHandler.NewZagLogicDeclare(conf.OutSiteRecallMetaFetcherMerge).SetClass(empty.EmptyLogic{}).
		AddPreLogic(kbBingRecall).AddPreLogic(kbSerperRecall).AddPreLogic(kbQuarkRecall).AddPreLogic(kbRecallOutSiteSourceMerge).AddPreLogic(kbKexinRecall)
	var outSiteLevelMetaFetcher = zagHandler.NewZagLogicDeclare(conf.OutSiteRecallLevelMetaFetcher).SetClass(meta_fetcher.OutSiteLevelMetaFetcherLogic{}).
		AddPreLogic(outSiteMetaFetcherMerge)
	// recall - 站内召回 & 站内用户召回 & 站内同问题下其他回答扩充  ======
	// 知乎站内内容 metaFetcher，为了 recallMerge 时计算相似度分数用标题 + 正文
	var kbZhihuRecall = zagHandler.NewZagLogicDeclare(conf.KbZhihuRecallLogic).SetClass(recall.KbZhihuRecallLogic{})
	var kbZhihuA4Recall = zagHandler.NewZagLogicDeclare(conf.KbZhihuA4RecallLogic).SetClass(recall.KbZhihuRecallLogic{})
	var kbZhihuSameQuestionAnswerRecall = zagHandler.NewZagLogicDeclare(conf.KbSameQuestionAnswerAppendLogic).SetClass(recall.KbSameQuestionAnswerAppendLogic{}).AddPreLogic(kbZhihuRecall)
	var kbZhihuRecallMetaFetcherMerge = zagHandler.NewZagLogicDeclare(conf.KbZhihuRecallMetaFetcherMergeLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(kbZhihuSameQuestionAnswerRecall).AddPreLogic(kbZhihuA4Recall)
	var kbZhihuRecallMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbZhihuRecallMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).AddPreLogic(kbZhihuRecallMetaFetcherMerge)
	var kbZhihuRecallTagFetcherLogic = zagHandler.NewZagLogicDeclare(conf.KbZhihuRecallTagFetcherLogic).SetClass(meta_fetcher.TagCoreMetaFetcherLogic{}).AddPreLogic(kbZhihuRecallMetaFetcherMerge)
	var kbRecallZhihuSourceMerge = zagHandler.NewZagLogicDeclare(conf.KbRecallZhihuSourceMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(kbZhihuRecallMetaFetcher).AddPreLogic(kbZhihuRecallTagFetcherLogic)
	// recall - 个人知识库召回 ======
	var personalKnowledgeBaseRumRecall = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseRumRecallLogic).SetClass(recall.RumRecallLogic{})
	var personalKnowledgeBaseRuceneRecall = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseRuceneRecallLogic).SetClass(recall.RuceneLogic{})
	var personalKnowledgeBaseRecallMerge = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseRecallMergeLogic).SetClass(empty.EmptyLogic{}).
		AddPreLogic(personalKnowledgeBaseRumRecall).AddPreLogic(personalKnowledgeBaseRuceneRecall)
	var personalKnowledgeBaselMetaFetcher = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseRecallMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).AddPreLogic(personalKnowledgeBaseRecallMerge)
	var personalKnowledgeBaselVisibilityFetcher = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseVisibilityMetaFetcherLogic).SetClass(meta_fetcher.KnowledgeBaseVisibilityMetaFetcherLogic{}).AddPreLogic(personalKnowledgeBaseRecallMerge)
	var personalKnowledgeBaseMergeLogic = zagHandler.NewZagLogicDeclare(conf.PersonalKnowledgeBaseMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).
		AddPreLogic(personalKnowledgeBaselMetaFetcher).AddPreLogic(personalKnowledgeBaselVisibilityFetcher)
	// recall - 创作者召回 ======
	var authorRecallLogic = zagHandler.NewZagLogicDeclare(conf.AuthorSearchRecallLogic).SetClass(recall.RumRecallLogic{})
	var authorSelfRecallLogic = zagHandler.NewZagLogicDeclare(conf.AuthorSearchSelfRecallLogic).SetClass(recall.ForwardIndexRecallLogic{})
	var authorSearchMergeLogic = zagHandler.NewZagLogicDeclare(conf.AuthorSearchMergeLogic).SetClass(ai_tab_rerank.AuthorMergeLogic{}).AddPreLogic(authorRecallLogic).AddPreLogic(authorSelfRecallLogic)
	// recall - 内部文档召回 ======
	var internalKnowledgeBaseRumRecall = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRumRecallLogic).SetClass(recall.RumRecallLogic{})
	var internalKnowledgeBaseRuceneRecall = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRuceneRecallLogic).SetClass(recall.RuceneLogic{})
	var internalKnowledgeBaseRecallMetaFetcherMerge = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRecallMetaFetcherMergeLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(internalKnowledgeBaseRumRecall).AddPreLogic(internalKnowledgeBaseRuceneRecall)
	var internalKnowledgeBaseRecallMetaFetcher = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRecallMetaFetcherLogic).SetClass(meta_fetcher2.InternalDocMetaFetcherLogic{}).AddPreLogic(internalKnowledgeBaseRecallMetaFetcherMerge)
	var internalKnowledgeBaseRecallSimMerge = zagHandler.NewZagLogicDeclare(conf.InternalKnowledgeBaseRecallSimMergeLogic).SetClass(merge.KbRecallSourceSimilarLogic{}).AddPreLogic(internalKnowledgeBaseRecallMetaFetcher)

	stageKbRecall.AddLogics(
		mountDoc2SpecifiedDocRecall, mountDoc2SpecifiedDocMetaFetcher, mountDoc2SpecifiedDocInternalMetaFetcher, kbZhihuAuthorDocRecall, KbZhihuAuthorDocSourceMerge,
		kbPaperRecall, kbReplenishArxivRecall, paperMetaFetcherMerge, paperMetaFetcher, paperSourceMergeLogic,
		kbZhihuRecall, kbZhihuA4Recall, kbZhihuSameQuestionAnswerRecall, kbZhihuRecallMetaFetcherMerge, kbZhihuRecallMetaFetcher, kbZhihuRecallTagFetcherLogic, kbRecallZhihuSourceMerge,
		kbBingRecall, kbQuarkRecall, kbSerperRecall, kbKexinRecall,
		outSiteRuceneRecallLogic, outSiteRumRecallLogic, kbRecallOutSiteSourceMerge, outSiteMetaFetcherMerge, outSiteLevelMetaFetcher,
		authorRecallLogic, authorSelfRecallLogic, authorSearchMergeLogic,
		personalKnowledgeBaseRumRecall, personalKnowledgeBaseRuceneRecall, personalKnowledgeBaseRecallMerge, personalKnowledgeBaselMetaFetcher, personalKnowledgeBaselVisibilityFetcher, personalKnowledgeBaseMergeLogic,
		internalKnowledgeBaseRumRecall, internalKnowledgeBaseRuceneRecall, internalKnowledgeBaseRecallMetaFetcherMerge, internalKnowledgeBaseRecallSimMerge, internalKnowledgeBaseRecallMetaFetcher,
	)

	// 合并召回源
	var recallMergeStage = zagHandler.NewZagStageDeclare(conf.RecallMergeStage).AddPres(stageKbRecall)
	var kbRecallSourceMerge = zagHandler.NewZagLogicDeclare(conf.KbRecallSourceMergeLogic).SetClass(merge.KbRecallSourceMergeLogic{})
	recallMergeStage.AddLogics(kbRecallSourceMerge)

	//------- recall MetaFetcher---------
	var recallMetaFetcherStage = zagHandler.NewZagStageDeclare(conf.RecallMetaFetcherStage).AddPres(recallMergeStage)
	// 自身 meta fetcher
	var kbRecallMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{})
	// 自身互动计数
	var contentStatsFetcherLogic = zagHandler.NewZagLogicDeclare(conf.ContentStatsFetcherLogic).SetClass(meta_fetcher.ContentStatsFetcherLogic{})
	// 创作者标签 fetcher
	var authorTagFetcherLogic = zagHandler.NewZagLogicDeclare(conf.AuthorTagFetcherLogic).SetClass(meta_fetcher.AuthorTagCoreMetaFetcherLogic{}).AddPreLogic(kbRecallMetaFetcher)
	// 父节点 meta fetcher，回答获取问题的 contentInfo
	var kbRecallParentMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallParentMetaFetcherLogic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).AddPreLogic(kbRecallMetaFetcher)
	// 子节点 meta fetcher，问题获取其下 top1 个回答的 contentInfo
	var kbRecallChildMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallChildMetaFetcherLogic).SetClass(meta_fetcher.ChildContentCoreMetaFetcherLogic{}).AddPreLogic(kbRecallMetaFetcher)
	// 结果合并，问题映射成回答
	var kbRecallQuestion2AnswerLogic = zagHandler.NewZagLogicDeclare(conf.KbRecallQuestion2AnswerLogic).SetClass(mapping.Question2AnswerLogic{}).AddPreLogic(kbRecallParentMetaFetcher).AddPreLogic(kbRecallChildMetaFetcher)
	recallMetaFetcherStage.AddLogics(kbRecallMetaFetcher, contentStatsFetcherLogic, authorTagFetcherLogic, kbRecallParentMetaFetcher, kbRecallChildMetaFetcher, kbRecallQuestion2AnswerLogic)

	//------- 站内外内容管控过滤 filter---------
	var recallFilterStage = zagHandler.NewZagStageDeclare(conf.RecallFilterStage).AddPres(recallMetaFetcherStage)
	var recallInitMerge = zagHandler.NewZagLogicDeclare(conf.RecallInitMergeLogic).SetClass(empty.EmptyLogic{})
	var recallInitFilter = zagHandler.NewZagLogicDeclare(conf.RecallInitFilterLogic).SetClass(frameworkFilter.InitFilterLogic[any, any, any]{}).AddPreLogic(recallInitMerge)
	// 内容管控过滤
	var validContentRegulateFetcherLogic = zagHandler.NewZagLogicDeclare(conf.ValidContentRegulateFetcherLogic).SetClass(meta_fetcher.ContentRegulateLogic{}).
		AddPreLogic(recallInitFilter)
	var contentRegulateFilterLogic = zagHandler.NewZagLogicDeclare(conf.ContentRegulateFilterLogic).SetClass(filter.ContentRegulateFilterLogic{}).
		AddPreLogic(validContentRegulateFetcherLogic)
	// 内容为空过滤
	var emptyMetaFilter = zagHandler.NewZagLogicDeclare(conf.EmptyContentFilterLogic).SetClass(filter.EmptyMetaFilterLogic{}).
		AddPreLogic(recallInitFilter)
	// 内容可见性过滤
	var kbVisibilityFilter = zagHandler.NewZagLogicDeclare(conf.KbVisibilityFilterLogic).SetClass(filter.KbRecallVisibilityFilterLogic{}).
		AddPreLogic(recallInitFilter)
	// 站外低质量站点过滤
	var siteLevelFilter = zagHandler.NewZagLogicDeclare(conf.SiteLevelFilterLogic).SetClass(filter.KbRecallSiteLevelFilterLogic{}).
		AddPreLogic(recallInitFilter)
	// 内容黑名单过滤 KbRecallBlackListFilterLogic
	var recallBlacklistFetcher = zagHandler.NewZagLogicDeclare(conf.RecallBlackListFilterLogic).SetClass(filter.KbRecallBlackListFilterLogic{}).AddPreLogic(recallInitFilter)
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
		AddPreLogic(emptyMetaFilter).AddPreLogic(siteLevelFilter).AddPreLogic(recallSecurityContentFilter).AddPreLogic(contentRegulateFilterLogic).
		AddPreLogic(tagCoreFilterLogic).AddPreLogic(recallSimHashFilter).AddPreLogic(kbVisibilityFilter).AddPreLogic(recallBlacklistFetcher)
	recallFilterStage.AddLogics(recallInitMerge, recallInitFilter, emptyMetaFilter, siteLevelFilter, recallBlacklistFetcher, kbVisibilityFilter,
		recallSecurityValidContentFetcher, recallSecurityContentFilter, validContentRegulateFetcherLogic, contentRegulateFilterLogic,
		tagCoreFetcherLogic, tagCoreFilterLogic, recallSimHashFilter, recallPostFilter)

	//------响应阶段--------
	var stageResponse = zagHandler.NewZagStageDeclare(conf.ResponseStage).AddPres(recallFilterStage)
	var BuildResponse = zagHandler.NewZagLogicDeclare(conf.RecallResponseLogic).SetClass(response.BuildRecallResponseLogic{})
	var tracingRecordLogic = zagHandler.NewZagLogicDeclare(conf.RecallTracingRecordLogic).SetClass(finalizer.RecallTracingRecordLogic{}).AddPreLogic(BuildResponse)

	stageResponse.AddLogics(BuildResponse, tracingRecordLogic)

	stages := []*zagHandler.DeclareStage{
		stageRoot,
		queryMetaFetcherStage,
		stageKbRecall,
		recallMergeStage,
		stageResponse,
		recallMetaFetcherStage,
		recallFilterStage,
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
