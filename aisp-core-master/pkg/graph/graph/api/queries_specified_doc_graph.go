package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/suggest_query_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/word"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// QueriesSpecifiedDocGraph 指定文档相关词生成
func QueriesSpecifiedDocGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("queries_graph",
		entities.BuildGraphScene(graph_constant.ApiSuggestQueries, proto.SuggestQueriesType_SPECIFIED_DOC_RELATED.String()), "1.1")

	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare(conf.RootStage)
	var rootNode = zagHandler.NewZagLogicDeclare(conf.RootNodeLogic).SetClass(empty.EmptyRootLogic{})
	stageRoot.AddLogics(rootNode)

	//------召回阶段--------
	var specifiedDocRelatedWordRecallStage = zagHandler.NewZagStageDeclare(conf.SpecifiedDocRelatedWordRecallStage).AddPres(stageRoot)
	var specifiedDocRelatedWordRecall = zagHandler.NewZagLogicDeclare(conf.SpecifiedDocRelatedWordRecallLogic).SetClass(word.WordSpecifiedDocRecallOrGenLogic{})
	specifiedDocRelatedWordRecallStage.AddLogics(specifiedDocRelatedWordRecall)

	//------判断相关词是否可以召回--------
	// 如果不能召回 则需要调用模型进行生成
	var relatedWordIsExistStage = zagHandler.NewZagStageDeclare(conf.RelatedWordIsExistStage).AddPres(specifiedDocRelatedWordRecallStage)
	var relatedWordIsExist = zagHandler.NewZagLogicDeclare(conf.RelatedWordIsExistLogic).SetClass(word.WordExistPostLogic{})
	var relatedWordExistDefault = zagHandler.NewZagLogicDeclare(conf.RelatedWordExistDefaultLogic).SetClass(empty.EmptyLogic{}).AddPreLogic(relatedWordIsExist)
	relatedWordIsExistStage.AddLogics(relatedWordIsExist, relatedWordExistDefault)

	//------- recall MetaFetcher---------
	var recallMetaFetcherStage = zagHandler.NewZagStageDeclare(conf.RecallMetaFetcherStage)
	var contentCoreMetaFetcher = zagHandler.NewZagLogicDeclare(conf.ContentCoreMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).AddPreLogic(relatedWordIsExist)
	var contentCoreParentMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallParentMetaFetcherLogic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).AddPreLogic(contentCoreMetaFetcher)
	recallMetaFetcherStage.AddLogics(contentCoreMetaFetcher, contentCoreParentMetaFetcher)

	//------生成阶段--------
	var specifiedDocRelatedWordGenStage = zagHandler.NewZagStageDeclare(conf.SpecifiedDocRelatedWordGenStage).AddPres(recallMetaFetcherStage)
	var specifiedDocRelatedWordGen = zagHandler.NewZagLogicDeclare(conf.SpecifiedDocRelatedWordGenLogic).SetClass(word.WordSpecifiedDocRecallOrGenLogic{})
	specifiedDocRelatedWordGenStage.AddLogics(specifiedDocRelatedWordGen)

	var specifiedDocRelatedWordMergeStage = zagHandler.NewZagStageDeclare(conf.SpecifiedDocRelatedWordRecallMergeStage).AddPres(stageRoot)
	var specifiedDocRelatedWordMerge = zagHandler.NewZagLogicDeclare(conf.SpecifiedDocRelatedWordRecallMergeLogic).SetClass(empty.EmptyLogic{}).
		AddPreLogic(relatedWordExistDefault).AddPreLogic(specifiedDocRelatedWordGen)
	specifiedDocRelatedWordMergeStage.AddLogics(specifiedDocRelatedWordMerge)

	//------安全审核--------
	var relatedWordAnswerSecurityStage = zagHandler.NewZagStageDeclare(conf.RelatedWordAnswerSecurityStage).AddPres(specifiedDocRelatedWordMergeStage)
	var relatedWordSecurityReviewLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordSecurityReviewLogic).SetClass(security.SecurityReviewWordLogic{})
	var relatedWordSecurityPostLogic = zagHandler.NewZagLogicDeclare(conf.RelatedWordSecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(relatedWordSecurityReviewLogic)
	relatedWordAnswerSecurityStage.AddLogics(relatedWordSecurityReviewLogic, relatedWordSecurityPostLogic)

	//------Merge--------
	var stageMerge = zagHandler.NewZagStageDeclare(conf.MergeStage).AddPres(relatedWordAnswerSecurityStage)
	var wordMergeAndFilter = zagHandler.NewZagLogicDeclare(conf.WordMergeAndFilterLogic).SetClass(word.WordMergeAndFilterLogic{})
	stageMerge.AddLogics(wordMergeAndFilter)

	relatedWordIsExist.SetSelectEdge(map[string][]string{
		entities.Normal: {contentCoreMetaFetcher.Name},
		entities.Break:  {relatedWordExistDefault.Name},
	})

	relatedWordSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {wordMergeAndFilter.Name},
		entities.Break:  {wordMergeAndFilter.Name},
	})

	stages := []*zagHandler.DeclareStage{
		stageRoot,
		specifiedDocRelatedWordRecallStage, relatedWordIsExistStage, recallMetaFetcherStage, specifiedDocRelatedWordGenStage,
		specifiedDocRelatedWordMergeStage,
		relatedWordAnswerSecurityStage, stageMerge}

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
