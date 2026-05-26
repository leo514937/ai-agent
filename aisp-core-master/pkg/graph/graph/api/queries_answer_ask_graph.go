package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	bizWord "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/suggest_query_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/word"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// QueriesAnswerAskGraph Answer 相关追问词
func QueriesAnswerAskGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("queries_graph",
		entities.BuildGraphScene(graph_constant.ApiSuggestQueries, proto.SuggestQueriesType_ASK_AGAIN_RELATED.String()), "1.1")

	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare(conf.RootStage)
	var rootNode = zagHandler.NewZagLogicDeclare(conf.RootNodeLogic).SetClass(empty.EmptyRootLogic{})
	stageRoot.AddLogics(rootNode)

	// 相关追问词 ==================================================
	var relatedWordCacheStage = zagHandler.NewZagStageDeclare(conf.RelatedWordCacheStage).AddPres(stageRoot)
	var relatedWordCache = zagHandler.NewZagLogicDeclare(conf.RelatedWordGetCacheLogic).SetClass(bizWord.GetRelatedWordCacheLogic{})
	// 拆解 docId docType 伪造为 知乎召回内容
	relatedWordCacheStage.AddLogics(relatedWordCache)
	var relatedWordDisassemblyInfoStage = zagHandler.NewZagStageDeclare(conf.RelatedWordDisassemblyInfoStage).AddPres(relatedWordCacheStage)
	var relatedWordDisassemblyInfoLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordDisassemblyInfoStageLogic).SetClass(bizWord.RelatedWordDisassemblyInfoLogic{})
	relatedWordDisassemblyInfoStage.AddLogics(relatedWordDisassemblyInfoLogic)

	//------- 获取知乎站内内容的meta信息 ---------
	var stageRelatedWordMetaFetcher = zagHandler.NewZagStageDeclare(conf.RelatedWordMetaFetcherStage).AddPres(relatedWordDisassemblyInfoStage)
	// 自身 meta fetcher
	var relatedWordMetaFetcher = zagHandler.NewZagLogicDeclare(conf.RelatedWordMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{})
	// 父节点 meta fetcher，回答获取问题的 contentInfo
	var relatedWordParentMetaFetcher = zagHandler.NewZagLogicDeclare(conf.RelatedWordParentMetaFetcherLogic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).AddPreLogic(relatedWordMetaFetcher)
	// 子节点 meta fetcher，问题获取其下 top1 个回答的 contentInfo
	var relatedWordChildMetaFetcher = zagHandler.NewZagLogicDeclare(conf.RelatedWordChildMetaFetcherLogic).SetClass(meta_fetcher.ChildContentCoreMetaFetcherLogic{}).AddPreLogic(relatedWordMetaFetcher)
	// 传入doc 伪装为 知乎召回内容
	var relatedWordCovertLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordCovertLogic).SetClass(bizWord.RelatedWordContentCovertLogic{}).AddPreLogic(relatedWordParentMetaFetcher).AddPreLogic(relatedWordChildMetaFetcher)
	stageRelatedWordMetaFetcher.AddLogics(relatedWordMetaFetcher, relatedWordParentMetaFetcher, relatedWordChildMetaFetcher, relatedWordCovertLogic)

	//------生成阶段--------
	var relatedWordGenerateStage = zagHandler.NewZagStageDeclare(conf.RelatedWordChatGenerateStage).AddPres(stageRelatedWordMetaFetcher)
	var relatedWordGenerateChatLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordChatGenerateLogic).SetClass(generate.ChatLogic{}).SetTimeOut(300 * 1000)
	var chatAnswer2SentenceLogic = zagHandler.NewZagLogicDeclare(conf.Answer2SentenceLogic).SetClass(mapping.ChatAnswer2SentenceLogic{}).AddPreLogic(relatedWordGenerateChatLogic)
	relatedWordGenerateStage.AddLogics(relatedWordGenerateChatLogic, chatAnswer2SentenceLogic)

	//------安全审核&存储缓存--------
	var relatedWordAnswerSecurityStage = zagHandler.NewZagStageDeclare(conf.RelatedWordAnswerSecurityStage)
	var relatedWordSecurityReviewLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordSecurityReviewLogic).SetClass(security.SecurityReviewWordLogic{}).
		AddPreLogic(chatAnswer2SentenceLogic)
	var relatedWordSecurityPostLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordSecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(relatedWordSecurityReviewLogic)
	var saveRelatedWordCacheLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordSaveCacheLogic).SetClass(bizWord.SaveRelatedWordCacheLogic{}).
		AddPreLogic(relatedWordSecurityPostLogic)
	relatedWordAnswerSecurityStage.AddLogics(relatedWordSecurityReviewLogic, relatedWordSecurityPostLogic, saveRelatedWordCacheLogic)

	//------缓存判断--------
	var relatedWordCacheJudgeStage = zagHandler.NewZagStageDeclare(conf.RelatedWordCacheJudgeStage)
	var relatedWordNormalLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordNormalLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(saveRelatedWordCacheLogic)
	var relatedWordBreakLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordBreakLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(relatedWordCache)
	relatedWordCacheJudgeStage.AddLogics(relatedWordNormalLogic, relatedWordBreakLogic)

	relatedWordCache.SetSelectEdge(map[string][]string{
		entities.Break:  {relatedWordBreakLogic.Name},
		entities.Normal: {relatedWordDisassemblyInfoLogic.Name},
	})
	relatedWordSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {saveRelatedWordCacheLogic.Name},
		entities.Break:  {saveRelatedWordCacheLogic.Name},
	})

	//------Merge--------
	var stageMerge = zagHandler.NewZagStageDeclare(conf.MergeStage).AddPres(relatedWordCacheJudgeStage)
	var wordMergeAndFilter = zagHandler.NewZagLogicDeclare(conf.WordMergeAndFilterLogic).SetClass(word.WordMergeAndFilterLogic{})
	stageMerge.AddLogics(wordMergeAndFilter)

	stages := []*zagHandler.DeclareStage{
		stageRoot, relatedWordCacheStage, relatedWordDisassemblyInfoStage,
		stageRelatedWordMetaFetcher, relatedWordGenerateStage, relatedWordAnswerSecurityStage, relatedWordCacheJudgeStage, stageMerge}

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
