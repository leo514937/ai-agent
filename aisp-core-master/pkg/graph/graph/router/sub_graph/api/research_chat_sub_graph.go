package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/finalizer"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_agent/graph/conf_stage"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_agent/graph/logic/retrieval"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	conf2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/sub_graph/root_logic"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

// ResearchChatSubGraph 深度搜索Chat 子图(适用 Research)
func ResearchChatSubGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var apiConfigPath = zagHandler.GetApiConfigPath()
	var zagGraph = zagHandler.NewZagGraphDeclareWithInfo("research_chat_sub_graph", entities.BuildGraphScene(graph_constant.ApiResearchStreamChatSub, proto.ChatType_ZHIDA_AGENT.String()), "0.1", "zhoupengcheng,wangran", "直答-Router-DeepSearch回答", apiConfigPath)

	//------root阶段--------
	var rootStage = zagHandler.NewZagStageDeclare(conf.RootStage)
	var copyUserMeta = zagHandler.NewZagLogicDeclare(conf.CopyUserMetaLogic).SetClass(root.CopyUserMetaLogic{})
	var userMessage = zagHandler.NewZagLogicDeclare(conf.UserMessageLogic).SetClass(root.UserMessageLogic{}).SetStore(conf2.SourceQueryItemLogicStoreKey.String()).
		AddPreLogic(copyUserMeta)
	rootStage.AddLogics(copyUserMeta, userMessage)

	//------Research阶段--------
	var researchStage = zagHandler.NewZagStageDeclare(conf.ResearchStage).AddPres(rootStage)
	var research = zagHandler.NewZagLogicDeclare(conf.ResearchLogic).SetClass(root_logic.DeepSearchLogic{})
	var researchAfterHandler = zagHandler.NewZagLogicDeclare(conf.ResearchAfterHandlerLogic).SetClass(retrieval.KbDeepSearchAfterHandlerLogic{}).AddPreLogic(research)
	researchStage.AddLogics(research, researchAfterHandler)

	// 生成阶段配置
	var generateConfigStage = zagHandler.NewZagStageDeclare(conf.GenerateConfigStage).AddPres(researchStage)
	var generateConfigLogic = zagHandler.NewZagLogicDeclare(conf.GenerateConfigLogic).SetClass(mapping.StageConfigLogic{})
	generateConfigStage.AddLogics(generateConfigLogic)

	//------answer 生成阶段--------
	var answerGenerateStage = zagHandler.NewZagStageDeclare(conf.GenerateStage).AddPres(generateConfigStage)
	var streamChatLogic = zagHandler.NewZagLogicDeclare(conf.StreamChatLogic).SetClass(generate.StreamChatLogic{}).
		SetTimeOut(600 * 1000)
	answerGenerateStage.AddLogics(streamChatLogic)

	//------answer 安全审核--------
	var answerSecurityStage = zagHandler.NewZagStageDeclare(conf.AnswerSecurityStage).AddPres(answerGenerateStage)
	var answerSecurityPostBeforeLogic = zagHandler.NewZagLogicDeclare(conf.AnswerSecurityBeforePostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		SetStore(conf2.StreamChatResultStoreKey.String())
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
	var wordGenerateStage = zagHandler.NewZagStageDeclare(conf.WordGenerateStage)
	var recallRebootResp = zagHandler.NewZagLogicDeclare(conf.RecallRebootRespLogic).SetClass(recall.KbRecallRebootRespLogic{}).AddPreLogic(answerSecurityPostLogic)
	var chatLogic = zagHandler.NewZagLogicDeclare(conf.ChatLogic).SetClass(generate.ChatLogic{}).SetTimeOut(600 * 1000).AddPreLogic(recallRebootResp)
	var chatAnswer2SentenceLogic = zagHandler.NewZagLogicDeclare(conf.Answer2SentenceLogic).SetClass(mapping.ChatAnswer2SentenceLogic{}).AddPreLogic(chatLogic)
	wordGenerateStage.AddLogics(recallRebootResp, chatLogic, chatAnswer2SentenceLogic)

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
	var responseStage = zagHandler.NewZagStageDeclare(conf.ResponseStage).AddPres(answerSecurityUnPassStage, wordSecurityStage)
	var buildResponse = zagHandler.NewZagLogicDeclare(conf.ResponseLogic).SetClass(response.BuildResponseLogic{})
	var saveQueryResultLogic = zagHandler.NewZagLogicDeclare(conf.SaveQueryResultLogic).SetClass(finalizer.SaveQueryResultLogic{}).AddPreLogic(buildResponse)
	responseStage.AddLogics(buildResponse, saveQueryResultLogic)

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
		rootStage,
		researchStage,
		generateConfigStage,
		answerGenerateStage, answerSecurityStage, answerSecurityUnPassStage,
		wordGenerateStage, wordSecurityStage,
		responseStage,
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
