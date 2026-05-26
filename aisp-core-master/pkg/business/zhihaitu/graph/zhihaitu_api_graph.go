package graph

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/conf/zhihaitu_api_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/graph/logic/retrieval"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/condition"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

const ApiBizTypePostfix = "Api"

// ZhihaituApiGraph 和ZhihaituChatGraph的不同点在于这个图会同步等待最后结果
func ZhihaituApiGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("zhihaitu_api_graph", graph_constant.ApiZhihaituChat+"."+proto.ChatType_ZHIHAITU.String()+ApiBizTypePostfix, "1.1-test")

	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare(conf.RootStage)
	//------安全模块--------
	var securityStage = zagHandler.NewZagStageDeclare(conf.SecurityStage).AddPres(stageRoot)
	//------检索阶段--------
	var retrieveStage = zagHandler.NewZagStageDeclare(conf.RetrieveStage).AddPres(securityStage)
	//------生成阶段--------
	var generateStage = zagHandler.NewZagStageDeclare(conf.GenerateStage).AddPres(securityStage)
	//------响应阶段--------
	var responseStage = zagHandler.NewZagStageDeclare(conf.ResponseStage).AddPres(securityStage).AddPres(generateStage)
	//------logger阶段--------

	//================算子声明================
	//-------request算子-------
	var userMessage = zagHandler.NewZagLogicDeclare(conf.UserMessageLogic).SetClass(root.UserMessageLogic{})

	//-------安全模块算子-------
	var redLine = zagHandler.NewZagLogicDeclare(conf.RedLineLogic).SetClass(security.RedLineLogic{})
	var faq = zagHandler.NewZagLogicDeclare(conf.FaqLogic).SetClass(security.FAQLogic{})
	var questionSecurityReview = zagHandler.NewZagLogicDeclare(conf.QuestionSecurityReviewLogic).SetClass(security.SecurityReviewBaseLogic{}).AddPreLogic(redLine)
	var securityCondition = zagHandler.NewZagLogicDeclare(conf.SecurityConditionLogic).
		SetClass(condition.IfElseMultiConditionLogic{}).AddPreLogic(redLine).AddPreLogic(faq)

	var questionSecurityReviewCondition = zagHandler.NewZagLogicDeclare(conf.QuestionSecurityReviewConditionLogic).
		SetClass(condition.IfElseConditionLogic{}).AddPreLogic(securityCondition)

	//-------检索算子-----------
	var retrievalLogic = zagHandler.NewZagLogicDeclare(conf.RetrievalLogic).SetClass(empty.EmptyBaseLogic{}).AddPreLogic(questionSecurityReviewCondition)
	var retrieveBing12371 = zagHandler.NewZagLogicDeclare(conf.RetrievalBing12371Logic).SetClass(retrieval.ExternalSiteableRetrievalLogic{}).AddPreLogic(retrievalLogic)
	var retrieveBingGov = zagHandler.NewZagLogicDeclare(conf.RetrievalBingGovLogic).SetClass(retrieval.ExternalSiteableRetrievalLogic{}).AddPreLogic(retrievalLogic)
	var retrieveBingNews = zagHandler.NewZagLogicDeclare(conf.RetrievalBingNewsLogic).SetClass(retrieval.ExternalSiteableRetrievalLogic{}).AddPreLogic(retrievalLogic)
	var retrieveBingXinhuanet = zagHandler.NewZagLogicDeclare(conf.RetrievalBingXinghuanetLogic).SetClass(retrieval.ExternalSiteableRetrievalLogic{}).AddPreLogic(retrievalLogic)
	var retrieveBingCctv = zagHandler.NewZagLogicDeclare(conf.RetrievalBingCctvLogic).SetClass(retrieval.ExternalSiteableRetrievalLogic{}).AddPreLogic(retrievalLogic)
	var retrieveBingPeople = zagHandler.NewZagLogicDeclare(conf.RetrievalBingPeopleLogic).SetClass(retrieval.ExternalSiteableRetrievalLogic{}).AddPreLogic(retrievalLogic)

	var retrieveMergeLogic = zagHandler.NewZagLogicDeclare(conf.RetrievalMergeLogic).SetClass(retrieval.RetrievalMergeLogic{}).
		AddPreLogic(retrieveBing12371).AddPreLogic(retrieveBingGov).AddPreLogic(retrieveBingNews).AddPreLogic(retrieveBingXinhuanet).AddPreLogic(retrieveBingCctv).AddPreLogic(retrieveBingPeople)
	//-------生成算子-------

	var queryPrompt = zagHandler.NewZagLogicDeclare(conf.QueryPromptLogic).SetClass(prompt.QueryPromptBaseLogic{}).AddPreLogic(retrieveMergeLogic)

	var chatLogic = zagHandler.NewZagLogicDeclare(conf.ChatLogic).SetClass(generate.ChatByModelGatewayLogic{}).AddPreLogic(queryPrompt)

	var emptyLogic = zagHandler.NewZagLogicDeclare(conf.EmptyLogic).SetClass(empty.EmptyBaseLogic{}).AddPreLogic(securityCondition)

	var answerSecurityReview = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityReviewLogic).SetClass(security.SecurityReviewBaseLogic{}).
		AddPreLogic(chatLogic).AddPreLogic(emptyLogic)

	var emptyLogic1 = zagHandler.NewZagLogicDeclare(conf.Empty1Logic).SetClass(empty.EmptyBaseLogic{}).AddPreLogic(questionSecurityReviewCondition)

	//-------响应算子-------
	var buildResponse = zagHandler.NewZagLogicDeclare(conf.ResponseLogic).SetClass(response.BuildChatResponseBaseLogic{})

	//================条件依赖===================
	securityCondition.SetSelectEdge(map[string][]string{
		entities.Normal: {questionSecurityReviewCondition.Name},
		entities.Break:  {emptyLogic.Name},
	})

	questionSecurityReviewCondition.SetSelectEdge(map[string][]string{
		entities.Normal: {retrievalLogic.Name},
		entities.Break:  {emptyLogic1.Name},
	})

	//================流程添加算子================
	stageRoot.AddLogics(userMessage)
	securityStage.AddLogics(redLine, faq, questionSecurityReview)
	retrieveStage.AddLogics(retrievalLogic, retrieveBing12371, retrieveBingGov, retrieveBingNews, retrieveBingXinhuanet, retrieveBingCctv, retrieveBingPeople, retrieveMergeLogic)
	generateStage.AddLogics(securityCondition, questionSecurityReviewCondition, queryPrompt, chatLogic, answerSecurityReview, emptyLogic, emptyLogic1)
	responseStage.AddLogics(buildResponse)

	stages := []*zagHandler.DeclareStage{
		stageRoot, securityStage, retrieveStage, generateStage, responseStage,
	}

	// 为算子添加 config
	for _, stage := range stages {
		for _, logic := range stage.LogicsPre {
			logic.AddConfigs(conf.LogicStaticConfigMap[logic.Name])
		}
	}

	//把base算子、流程声明 加载到图中
	zagGraph.AddStagesWithLogics(stages...)

	//-------api 声明 >> 业务逻辑图-------
	return zagHandler.ApiDeclare2Graph[C, U, I](zagGraph)
}
