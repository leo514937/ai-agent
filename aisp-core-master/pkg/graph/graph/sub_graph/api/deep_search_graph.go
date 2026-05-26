package api

import (
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/conf_stage"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/sub_graph/sub_logic"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// DeepSearchGraph 直答DeepSearch图
func DeepSearchGraph[C, U, I any](bizType string) *graph.Graph {
	//========图声明========
	var apiConfigPath = zagHandler.GetApiConfigPath()
	var zagGraph = zagHandler.NewZagGraphDeclareWithInfo("deepsearch_graph", entities.BuildGraphScene(graph_constant.ApiDeepSearch, bizType), "0.1", "wangran", "直答deepSearch子图", apiConfigPath)

	//------recall阶段--------
	var stageKbRecall = zagHandler.NewZagStageDeclare(conf.RootStage)
	var deepSearchRecall = zagHandler.NewZagLogicDeclare(conf.DeepSearchRecallLogic).SetClass(sub_logic.DeepSearchRecallLogic{})
	stageKbRecall.AddLogics(deepSearchRecall)

	//-------MetaFetcher---------
	var recallMetaFetcherStage = zagHandler.NewZagStageDeclare(conf.RecallMetaFetcherStage).AddPres(stageKbRecall)
	// 自身 meta fetcher
	var kbRecallMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallMetaFetcherLogic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{})
	// 自身互动计数
	var contentStatsFetcher = zagHandler.NewZagLogicDeclare(conf.ContentStatsFetcherLogic).SetClass(meta_fetcher.ContentStatsFetcherLogic{})
	// 父节点 meta fetcher，回答获取问题的 contentInfo
	var kbRecallParentMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallParentMetaFetcherLogic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).AddPreLogic(kbRecallMetaFetcher)
	var kbAuthorNameMetaFetcher = zagHandler.NewZagLogicDeclare(conf.KbRecallAuthorMetaFetcherLogic).SetClass(meta_fetcher.AuthorInfoFetchLogic{}).AddPreLogic(kbRecallMetaFetcher)
	var documentFetcher = zagHandler.NewZagLogicDeclare(conf.DocumentFetcherLogic).SetClass(meta_fetcher.DocumentFetcherLogic{}).AddPreLogic(kbRecallParentMetaFetcher)
	var readMetaFetcher = zagHandler.NewZagLogicDeclare(conf.ReadFetcherLogic).SetClass(meta_fetcher.ReadMetaFetcherLogic{}).AddPreLogic(documentFetcher)
	recallMetaFetcherStage.AddLogics(kbRecallMetaFetcher, contentStatsFetcher, kbRecallParentMetaFetcher, kbAuthorNameMetaFetcher, documentFetcher, readMetaFetcher)

	//------响应阶段--------
	var stageResponse = zagHandler.NewZagStageDeclare(conf.ResponseStage).AddPres(recallMetaFetcherStage)
	var BuildResponse = zagHandler.NewZagLogicDeclare(conf.RecallResponseLogic).SetClass(response.BuildRecallResponseLogic{})

	stageResponse.AddLogics(BuildResponse)

	stages := []*zagHandler.DeclareStage{
		stageKbRecall,
		stageResponse,
		recallMetaFetcherStage,
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
