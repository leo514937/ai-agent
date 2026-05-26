package api

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/query_merge_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/query_merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// QueryMergeGraph QueryMerge 业务图
func QueryMergeGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("query_merge_graph",
		graph_constant.ApiBuildQuery+".all", "1.1")

	//================流程声明================

	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare(conf.RootStage)
	var userMessage = zagHandler.NewZagLogicDeclare(conf.UserMessageLogic).SetClass(root.UserMessageLogic{})
	stageRoot.AddLogics(userMessage)

	//------prepare阶段--------
	var stagePrepare = zagHandler.NewZagStageDeclare(conf.PrepareStage).AddPres(stageRoot)
	var chatHistory = zagHandler.NewZagLogicDeclare(conf.ChatHistoryLogic).SetClass(root.ChatHistoryLogic{})
	stagePrepare.AddLogics(chatHistory)

	//------空算子--------
	var emptyStage = zagHandler.NewZagStageDeclare(conf.EmptyStage).AddPres(stageRoot)
	var emptyLogic = zagHandler.NewZagLogicDeclare(conf.EmptyLogic).SetClass(empty.EmptyLogic{})
	emptyStage.AddLogics(emptyLogic)

	//------mapping阶段--------
	var stageMapping = zagHandler.NewZagStageDeclare(conf.MappingStage).AddPres(stagePrepare, emptyStage)
	var queryMerge = zagHandler.NewZagLogicDeclare(conf.QueryMergeLogic).SetClass(query_merge.QueryMergeLogic{})
	stageMapping.AddLogics(queryMerge)

	//------安全审核阶段--------
	var securityStage = zagHandler.NewZagStageDeclare(conf.SecurityStage).AddPres(stageMapping)
	var securityReviewOut = zagHandler.NewZagLogicDeclare(conf.SecurityReviewOutLogic).SetClass(security.SecurityReviewLogic{})

	var securityPost = zagHandler.NewZagLogicDeclare(conf.SecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).AddPreLogic(securityReviewOut)
	securityStage.AddLogics(securityReviewOut, securityPost)

	//------MergeResp阶段--------
	var stageResp = zagHandler.NewZagStageDeclare(conf.RespStage).AddPres(securityStage)
	var itemResp = zagHandler.NewZagLogicDeclare(conf.ItemRespLogic).SetClass(response.DefItemRespLogic{})
	stageResp.AddLogics(itemResp)

	// 条件边
	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {itemResp.Name},
		entities.Break:  {itemResp.Name},
	})

	stages := []*zagHandler.DeclareStage{
		stageRoot, stagePrepare, emptyStage, stageMapping, securityStage, stageResp,
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
