package api

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/suggest_query_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/word"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// QueriesGuidGraph 直达引导词
func QueriesGuidGraph[C, U, I any](bizType string) *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("queries_graph",
		entities.BuildGraphScene(graph_constant.ApiSuggestQueries, bizType), "1.0")

	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare(conf.RootStage)
	var userTags = zagHandler.NewZagLogicDeclare(conf.UserTagsLogic).SetClass(root.TagMemberLogic{})
	stageRoot.AddLogics(userTags)

	//------recall阶段--------
	var stageRecall = zagHandler.NewZagStageDeclare(conf.RecallStage).AddPres(stageRoot)
	// 算法生成词召回（问题、热榜问题、热点事件，自建 rum 索引）
	var wordGuideRecall = zagHandler.NewZagLogicDeclare(conf.WordGuideV2RecallLogic).SetClass(word.WordGuideRecallV2Logic{})
	stageRecall.AddLogics(wordGuideRecall)

	//------Merge--------
	var stageMerge = zagHandler.NewZagStageDeclare(conf.MergeStage).AddPres(stageRecall)
	var wordMergeAndFilter = zagHandler.NewZagLogicDeclare(conf.WordMergeAndFilterLogic).SetClass(word.WordMergeAndFilterLogic{})
	stageMerge.AddLogics(wordMergeAndFilter)

	stages := []*zagHandler.DeclareStage{
		stageRoot, stageRecall, stageMerge}

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
