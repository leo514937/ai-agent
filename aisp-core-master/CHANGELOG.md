# Changelog

* 记录下线图的编排信息

## 2024.5.21

- aiTab
```
package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/consumer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	commonFilter "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/filter"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/intention"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/query_merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	frameworkFilter "git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
	"github.com/spf13/cast"
)

func StreamChatAiTabV2Graph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("chat_graph", entities.ApiStreamChat+"."+proto.ChatType_AI_TAB.String(), "2.1")

	//================空Resp=================

	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare("root")
	var copyUserMeta = zagHandler.NewZagLogicDeclare("CopyUserMeta").SetClass(root.CopyUserMetaLogic{}).
		AddConfig(conf.ConfigApi, entities.ApiStreamChat).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyQueryText,
			graph_macro.ZagKeyMemberId, graph_macro.ZagKeyScene, graph_macro.ZagKeySessionId))

	var UserMessage = zagHandler.NewZagLogicDeclare("UserMessage").SetClass(root.UserMessageLogic{}).SetStore(conf.SourceQueryItemLogicStoreKey.String()).
		AddPreLogic(copyUserMeta)

	stageRoot.AddLogics(copyUserMeta, UserMessage)

	//------prepare阶段--------
	var stagePrepare = zagHandler.NewZagStageDeclare("prepareStage").AddPres(stageRoot)
	// 历史记录
	var chatHistory = zagHandler.NewZagLogicDeclare("ChatHistory").SetClass(root.ChatHistoryLogic{})
	// 召回方案(默认 知乎)
	var recallOption = zagHandler.NewZagLogicDeclare("RecallOption").SetClass(root.RecallOptionLogic{}).
		AddConfig(conf.SummaryRecallDefOption.ToConvert(), cast.ToString(int32(proto.ChatType_AI_TAB)))
	stagePrepare.AddLogics(chatHistory, recallOption)

	//------空算子--------
	var emptyStage1 = zagHandler.NewZagStageDeclare("emptyStage1").AddPres(stageRoot)
	var emptyLogic1 = zagHandler.NewZagLogicDeclare("empty1").SetClass(empty.EmptyLogic{})
	emptyStage1.AddLogics(emptyLogic1)

	//------安全模块--------
	var securityStage = zagHandler.NewZagStageDeclare("SecurityRedLineStage").AddPres(emptyStage1, stagePrepare)
	var emptyLogicSafe = zagHandler.NewZagLogicDeclare("SecurityRedLineEmptySafe").SetClass(empty.EmptyLogic{})
	var redLine = zagHandler.NewZagLogicDeclare("SecurityRedLine").SetClass(security.RedLineLogic{}).AddPreLogic(emptyLogicSafe).
		AddConfig(conf.ConfigOutputNames, graph_macro.ZagKeyRedLineAnswer)

	var securityRedLinePost = zagHandler.NewZagLogicDeclare("SecurityRedLinePost").SetClass(security_post.StaticQAJudgeLogic{}).AddPreLogic(redLine)
	var redLineEmptyDefLogic = zagHandler.NewZagLogicDeclare("RedLineEmptyDefLogic").SetClass(empty.EmptyLogic{}).AddPreLogic(securityRedLinePost)
	securityStage.AddLogics(emptyLogicSafe, redLine, securityRedLinePost, redLineEmptyDefLogic)

	//------QueryMerge阶段--------
	var stageQueryMerge = zagHandler.NewZagStageDeclare("QueryMergeStage")
	var queryMerge = zagHandler.NewZagLogicDeclare("QueryMerge").SetClass(query_merge.QueryMergeLogic{}).AddPreLogic(securityRedLinePost)
	stageQueryMerge.AddLogics(queryMerge)

	//------意图识别判断--------
	var intentionStage = zagHandler.NewZagStageDeclare("IntentionStage")
	var searchIntentionLogic = zagHandler.NewZagLogicDeclare("SearchIntention").SetClass(meta_fetcher.SearchIntentionLogic{}).
		AddPreLogic(queryMerge)
	var intentionJudgeLogic = zagHandler.NewZagLogicDeclare("IntentionJudge").SetClass(intention.IntentionDefJudgeLogic{}).
		AddPreLogic(searchIntentionLogic)
	// 意图识别默认空算子
	var intentionEmptyDefLogic = zagHandler.NewZagLogicDeclare("IntentionEmptyDefLogic").SetClass(empty.EmptyLogic{}).AddPreLogic(intentionJudgeLogic)
	intentionStage.AddLogics(searchIntentionLogic, intentionJudgeLogic, intentionEmptyDefLogic)

	//------recall 阶段--------

	//------recall阶段--------
	var stageKbRecall = zagHandler.NewZagStageDeclare("kbRecall")
	var kbZhihuRecall = zagHandler.NewZagLogicDeclare("KbZhihuRecall").SetClass(recall.KbZhihuRecallLogic{}).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), util.GetJSONIgnoreError(conf.ZSearchRecallConfig{})).
		AddConfig(conf.SummaryRecallOrderGroup.ToConvert(), "0").
		AddPreLogic(intentionJudgeLogic)
	var kbRecallSourceMerge = zagHandler.NewZagLogicDeclare("KbRecallSourceMerge").SetClass(empty.EmptyLogic{}).AddPreLogic(kbZhihuRecall)
	stageKbRecall.AddLogics(kbZhihuRecall, kbRecallSourceMerge)

	//------- recall MetaFetcher---------
	var recallMetaFetcherStage = zagHandler.NewZagStageDeclare("RecallMetaFetcherStage").AddPres(stageKbRecall)
	// 召回(MetaFetcher)
	var kbRecallMetaFetcher = zagHandler.NewZagLogicDeclare("kbRecallMetaFetcher").SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{})
	recallMetaFetcherStage.AddLogics(kbRecallMetaFetcher)

	// 过滤内外部召回
	var recallIoFilterStage = zagHandler.NewZagStageDeclare("RecallIoFilterStage").AddPres(recallMetaFetcherStage)
	// 内部召回过滤
	var recallInsideFilter = zagHandler.NewZagLogicDeclare("RecallInsideFilter").SetClass(recall.KbRecallIoFilterLogic{}).
		AddConfig(conf.SummaryRecallFilterIo.ToConvert(), "true")
	recallIoFilterStage.AddLogics(recallInsideFilter)

	//------- 管控过滤 filter---------
	var stageFilter = zagHandler.NewZagStageDeclare("StageFilter")
	var initFilter = zagHandler.NewZagLogicDeclare("InitFilter").SetClass(frameworkFilter.InitFilterLogic[any, any, any]{}).
		AddConfig("filterReasonMap", "filterReasonMap").AddPreLogic(recallInsideFilter)
	var validContentRegulateFetcherLogic = zagHandler.NewZagLogicDeclare("ValidContentRegulateFetcher").SetClass(meta_fetcher.ContentRegulateLogic{}).
		AddPreLogic(initFilter).AddConfig(conf.ConfigRegulateSceneCode, rpc.SceneCodeSearch).AddConfig(conf.ConfigRegulateSubSceneCode, rpc.SubSceneCodeDEFAULT)
	var contentRegulateFilterLogic = zagHandler.NewZagLogicDeclare("ContentRegulateFilter").SetClass(commonFilter.ContentRegulateFilterLogic{}).
		AddPreLogic(validContentRegulateFetcherLogic).
		AddConfig(conf.ConfigRegulateKey, rpc.VisitorCirculate)
	var postFilter = zagHandler.NewZagLogicDeclare("PostFilter").SetClass(frameworkFilter.FilterPostLogic[any, any, any]{}).
		AddConfig("filterReasonMap", "filterReasonMap").AddPreLogic(contentRegulateFilterLogic)
	stageFilter.AddLogics(initFilter, validContentRegulateFetcherLogic, contentRegulateFilterLogic, postFilter)

	//------recall handle 阶段--------
	var kbRecallHandleStage = zagHandler.NewZagStageDeclare("KbRecallHandleStage").AddPres(recallMetaFetcherStage)
	// 站内召回分块和重排序
	var kbInsideRecallChunkAndReRank = zagHandler.NewZagLogicDeclare("KbInsideRecallChunkAndReRank").SetClass(recall.KbRecallChunkAndReRankLogic{}).AddPreLogic(postFilter)
	// 召回分块内容阶段
	var kbInsideRecallChunkLimit = zagHandler.NewZagLogicDeclare("kbInsideRecallChunkLimit").SetClass(recall.KbRecallChunkLimitLogic{}).
		AddConfig(conf.SummaryRecallSource.ToConvert(), conf.KbSourceZhihu.String()).AddPreLogic(kbInsideRecallChunkAndReRank)
	// 召回统一Merge
	var KbMergeAndLimitRecall = zagHandler.NewZagLogicDeclare("KbMergeAndLimitRecall").SetClass(recall.KbRecallMergeAndLimitLogic{}).AddPreLogic(kbInsideRecallChunkAndReRank).AddPreLogic(kbInsideRecallChunkLimit)
	// 转换Recall 结果为字符串
	var recallRes2ConvertString = zagHandler.NewZagLogicDeclare("RecallRes2ConvertString").SetClass(recall.KbRecallConvert2StringLogic{}).AddPreLogic(KbMergeAndLimitRecall)
	// 判断是否满足召回条件 如果不满足则降级到ai对话
	var kbRecallPost = zagHandler.NewZagLogicDeclare("kbRecallPost").SetClass(recall.KbRecallJudgeLogic{}).AddPreLogic(recallRes2ConvertString)
	kbRecallHandleStage.AddLogics(kbInsideRecallChunkAndReRank, kbInsideRecallChunkLimit, KbMergeAndLimitRecall, recallRes2ConvertString, kbRecallPost)

	//------安全审核阶段--------
	var securityQueryStage = zagHandler.NewZagStageDeclare("SecurityQueryStage")
	// AI Query
	var securityQueryByAiReviewOutProxy = zagHandler.NewZagLogicDeclare("SecurityQueryByAiReviewOutProxy").SetClass(empty.EmptyLogic{}).
		AddPreLogic(intentionEmptyDefLogic).AddPreLogic(kbRecallPost)
	var securityQueryByAiReviewOut = zagHandler.NewZagLogicDeclare("SecurityQueryByAiReviewOut").SetClass(security.SecurityReviewLogic{}).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceAiQuery.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
			Scene:           proto.ChatType_AI_TAB.String(),
			StoreSource:     conf.SourceQueryItemLogicStoreKey,
		}.ToJsonString()).AddPreLogic(securityQueryByAiReviewOutProxy)
	// Summary Query
	var securityQueryBySummaryReviewOut = zagHandler.NewZagLogicDeclare("SecurityQueryBySummaryReviewOut").SetClass(security.SecurityReviewLogic{}).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
			Scene:           proto.ChatType_AI_TAB.String(),
			StoreSource:     conf.SourceQueryItemLogicStoreKey,
		}.ToJsonString()).AddPreLogic(kbRecallPost)
	var securityQueryByAiPost = zagHandler.NewZagLogicDeclare("SecurityQueryByAiPost").SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(securityQueryByAiReviewOut)
	var securityQueryBySummaryPost = zagHandler.NewZagLogicDeclare("SecurityQueryBySummaryPost").SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(securityQueryBySummaryReviewOut)
	var securityQueryByAiEmptyDefLogic = zagHandler.NewZagLogicDeclare("SecurityQueryByAiEmptyDefLogic").SetClass(empty.EmptyLogic{}).AddPreLogic(securityQueryByAiPost)
	var securityQueryBySummaryEmptyDefLogic = zagHandler.NewZagLogicDeclare("SecurityQueryBySummaryEmptyDefLogic").SetClass(empty.EmptyLogic{}).AddPreLogic(securityQueryBySummaryPost)
	securityQueryStage.AddLogics(securityQueryByAiReviewOutProxy, securityQueryByAiReviewOut, securityQueryBySummaryReviewOut,
		securityQueryByAiPost, securityQueryBySummaryPost, securityQueryByAiEmptyDefLogic, securityQueryBySummaryEmptyDefLogic)

	//------拼接Prompt阶段--------
	promptAi := "{{.Query}}"
	promptSummary := "RULES:\n" +
		"1. 回答必须(MUST)使用中文。\n" +
		"2. 直接提供帮助即可，不要说抱歉、对不起等带有歉意的表述。\n" +
		"3. 回答不要提及“知识库”、“根据知识库”等，有类似都表达请用“据我所知”代替。\n\n" +
		"根据Knowledge完成对话：\n\n" +
		"Knowledge:\n{{.Knowledge}}\n\n" +
		"问题: {{.Query}}\n" +
		"回答:"
	var stagePrompt = zagHandler.NewZagStageDeclare("PromptStage")
	var buildByAiPrompt = zagHandler.NewZagLogicDeclare("BuildByAiPrompt").SetClass(prompt.BuildPromptLogic{}).
		AddConfig(conf.ConfigPrompt, promptAi).
		AddConfig(conf.ConfigPromptID, "1001").AddPreLogic(securityQueryByAiPost)
	var buildBySummaryPrompt = zagHandler.NewZagLogicDeclare("BuildBySummaryPrompt").SetClass(prompt.BuildPromptLogic{}).
		AddConfig(conf.ConfigPrompt, promptSummary).
		AddConfig(conf.ConfigPromptID, "1002").AddPreLogic(securityQueryBySummaryPost)
	var knowledgeEnhance = zagHandler.NewZagLogicDeclare("KnowledgeEnhance").SetClass(security.KnowledgeEnhanceLogic{}).AddPreLogic(buildBySummaryPrompt)
	stagePrompt.AddLogics(buildByAiPrompt, buildBySummaryPrompt, knowledgeEnhance)

	//------生成阶段--------
	var stageGenerate = zagHandler.NewZagStageDeclare("GenerateStage")
	var streamAiChatLogic = zagHandler.NewZagLogicDeclare("StreamChatAiLogic").SetClass(generate.StreamChatLogic{}).SetTimeOut(300*1000).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.ChatConfig{
			ChatHistoryType: conf.ChatHistoryStrLengthLimit,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceAiAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			},
		}.ToJsonString()).AddPreLogic(buildByAiPrompt)
	var streamSummaryChatLogic = zagHandler.NewZagLogicDeclare("StreamChatSummaryLogic").SetClass(generate.StreamChatLogic{}).SetTimeOut(300*1000).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.ChatConfig{
			ChatHistoryType: conf.ChatHistoryStrLengthLimit,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			},
		}.ToJsonString()).AddPreLogic(knowledgeEnhance)
	stageGenerate.AddLogics(streamAiChatLogic, streamSummaryChatLogic)

	//------安全审核阶段--------
	var securityAnswerStage = zagHandler.NewZagStageDeclare("SecurityAnswerStage")
	// AI Answer
	var securityAnswerByAiReviewOut = zagHandler.NewZagLogicDeclare("SecurityAnswerByAiReviewOut").SetClass(security.SecurityReviewLogic{}).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:         rpc.RiskCheckSourceAiAnswer.ToConvert(),
			ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:            proto.ChatType_AI_TAB.String(),
			ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
		}.ToJsonString()).AddPreLogic(streamAiChatLogic)
	// Summary Answer
	var securityAnswerBySummaryReviewOut = zagHandler.NewZagLogicDeclare("SecurityAnswerBySummaryReviewOut").SetClass(security.SecurityReviewLogic{}).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:         rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:            proto.ChatType_AI_TAB.String(),
			ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
		}.ToJsonString()).AddPreLogic(streamSummaryChatLogic)
	var securityAnswerByAiPost = zagHandler.NewZagLogicDeclare("SecurityAnswerByAiPost").SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(securityAnswerByAiReviewOut)
	var securityAnswerBySummaryPost = zagHandler.NewZagLogicDeclare("SecurityAnswerBySummaryPost").SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(securityAnswerBySummaryReviewOut)
	var securityAnswerByAiPostDefEmptyLogic = zagHandler.NewZagLogicDeclare("SecurityAnswerByAiPostDefEmptyLogic").SetClass(empty.EmptyLogic{}).
		AddPreLogic(securityAnswerByAiPost)
	var securityAnswerBySummaryPostDefEmptyLogic = zagHandler.NewZagLogicDeclare("SecurityAnswerBySummaryPostDefEmptyLogic").SetClass(empty.EmptyLogic{}).
		AddPreLogic(securityAnswerBySummaryPost)
	var securityAnswerByAiPostDefEmptyLogicByBreak = zagHandler.NewZagLogicDeclare("SecurityAnswerByAiPostDefEmptyLogicByBreak").SetClass(empty.EmptyLogic{}).
		AddPreLogic(securityAnswerByAiPost)
	var securityAnswerBySummaryPostDefEmptyLogicByBreak = zagHandler.NewZagLogicDeclare("SecurityAnswerBySummaryPostDefEmptyLogicByBreak").SetClass(empty.EmptyLogic{}).
		AddPreLogic(securityAnswerBySummaryPost)
	securityAnswerStage.AddLogics(securityAnswerByAiReviewOut, securityAnswerBySummaryReviewOut, securityAnswerByAiPost,
		securityAnswerBySummaryPost, securityAnswerByAiPostDefEmptyLogic, securityAnswerBySummaryPostDefEmptyLogic,
		securityAnswerByAiPostDefEmptyLogicByBreak, securityAnswerBySummaryPostDefEmptyLogicByBreak)

	//------空算子Query --------
	var emptyStageByResp = zagHandler.NewZagStageDeclare("EmptyStageByResp")
	var emptyLogicByResp = zagHandler.NewZagLogicDeclare("EmptyLogicByResp").SetClass(empty.EmptyLogic{}).
		AddPreLogic(redLineEmptyDefLogic).AddPreLogic(securityQueryByAiEmptyDefLogic).AddPreLogic(securityQueryBySummaryEmptyDefLogic).
		AddPreLogic(securityAnswerByAiPostDefEmptyLogic).AddPreLogic(securityAnswerBySummaryPostDefEmptyLogic).
		AddPreLogic(securityAnswerByAiPostDefEmptyLogicByBreak).AddPreLogic(securityAnswerBySummaryPostDefEmptyLogicByBreak)
	emptyStageByResp.AddLogics(emptyLogicByResp)

	//------响应阶段--------
	var stageResponse = zagHandler.NewZagStageDeclare("ResponseStage").AddPres(emptyStageByResp)
	var BuildResponse = zagHandler.NewZagLogicDeclare("Response").SetClass(response.BuildResponseLogic{}).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyRelevantQueries, graph_macro.ZagKeyCurrentAnswer))

	var SaveDialog = zagHandler.NewZagLogicDeclare("SaveDialog").SetClass(consumer.SaveDialogRecordLogic{}).AddPreLogic(BuildResponse).
		AddConfig(conf.ConfigInputNames, util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyCurrentAnswer))

	stageResponse.AddLogics(BuildResponse, SaveDialog)

	// Query 过红线必答
	securityRedLinePost.SetSelectEdge(map[string][]string{
		entities.Normal: {queryMerge.Name},
		entities.Break:  {redLineEmptyDefLogic.Name},
	})

	// 意图识别
	intentionJudgeLogic.SetSelectEdge(map[string][]string{
		// 闲聊
		proto.IntentionType_SMALL_TALKS.String(): {intentionEmptyDefLogic.Name},
		// 非闲聊
		proto.IntentionType_OUT_DOMAIN.String(): {kbZhihuRecall.Name},
		//proto.IntentionType_OUT_DOMAIN.String(): {kbBingRecall.Name, kbZhihuRecall.Name},
	})

	// kbRecallPost recall
	kbRecallPost.SetSelectEdge(map[string][]string{
		enums.Correlation.String():   {securityQueryBySummaryReviewOut.Name},
		enums.UnCorrelation.String(): {securityQueryByAiReviewOutProxy.Name},
	})

	// 安全接口审核 query
	securityQueryByAiPost.SetSelectEdge(map[string][]string{
		entities.Normal: {buildByAiPrompt.Name},
		entities.Break:  {securityQueryByAiEmptyDefLogic.Name},
	})
	securityQueryBySummaryPost.SetSelectEdge(map[string][]string{
		entities.Normal: {buildBySummaryPrompt.Name},
		entities.Break:  {securityQueryBySummaryEmptyDefLogic.Name},
	})

	// 安全接口审核 answer
	securityAnswerByAiPost.SetSelectEdge(map[string][]string{
		entities.Normal: {securityAnswerByAiPostDefEmptyLogic.Name},
		entities.Break:  {securityAnswerByAiPostDefEmptyLogicByBreak.Name},
	})
	securityAnswerBySummaryPost.SetSelectEdge(map[string][]string{
		entities.Normal: {securityAnswerBySummaryPostDefEmptyLogic.Name},
		entities.Break:  {securityAnswerBySummaryPostDefEmptyLogicByBreak.Name},
	})

	//把base算子、流程声明 加载到图中
	zagGraph.AddStagesWithLogics(stageRoot, stagePrepare, emptyStage1, securityStage, intentionStage,
		stageQueryMerge, stageKbRecall, recallMetaFetcherStage, recallIoFilterStage, stageFilter, kbRecallHandleStage, securityQueryStage,
		stagePrompt, stageGenerate, securityAnswerStage, emptyStageByResp, stageResponse)

	//-------api 声明 >> 业务逻辑图-------
	return zagHandler.ApiDeclare2Graph[C, U, I](zagGraph)
}

```

- searchTab
```
package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/consumer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	commonFilter "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/filter"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/query_merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	frameworkFilter "git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
	"github.com/spf13/cast"
)

func StreamChatSearchTabGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("chat_graph", entities.ApiStreamChat+"."+proto.ChatType_SEARCH_TAB.String(), "1.2")

	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare("root")
	var copyUserMeta = zagHandler.NewZagLogicDeclare("CopyUserMeta").SetClass(root.CopyUserMetaLogic{}).
		AddConfig(conf.ConfigApi, entities.ApiStreamChat).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyQueryText,
			graph_macro.ZagKeyMemberId, graph_macro.ZagKeyScene, graph_macro.ZagKeySessionId))

	var UserMessage = zagHandler.NewZagLogicDeclare("UserMessage").SetClass(root.UserMessageLogic{}).SetStore(conf.SourceQueryItemLogicStoreKey.String()).
		AddPreLogic(copyUserMeta)

	stageRoot.AddLogics(copyUserMeta, UserMessage)

	//------prepare阶段--------
	var stagePrepare = zagHandler.NewZagStageDeclare("prepare").AddPres(stageRoot)
	// 历史记录
	var chatHistory = zagHandler.NewZagLogicDeclare("ChatHistory").SetClass(root.ChatHistoryLogic{})
	// 召回方案(默认 知乎)
	var recallOption = zagHandler.NewZagLogicDeclare("RecallOption").SetClass(root.RecallOptionLogic{}).
		AddConfig(conf.SummaryRecallDefOption.ToConvert(), cast.ToString(int32(proto.ChatType_SEARCH_TAB)))
	stagePrepare.AddLogics(chatHistory, recallOption)

	//------空算子--------
	var emptyStage1 = zagHandler.NewZagStageDeclare("emptyStage1").AddPres(stageRoot)
	var emptyLogic1 = zagHandler.NewZagLogicDeclare("empty1").SetClass(empty.EmptyLogic{})
	emptyStage1.AddLogics(emptyLogic1)

	//------安全模块--------
	var securityStage = zagHandler.NewZagStageDeclare("security").AddPres(emptyStage1, stagePrepare)
	var emptyLogicSafe = zagHandler.NewZagLogicDeclare("emptySafe").SetClass(empty.EmptyLogic{})
	var redLine = zagHandler.NewZagLogicDeclare("redLine").SetClass(security.RedLineLogic{}).AddPreLogic(emptyLogicSafe)
	var securityReview = zagHandler.NewZagLogicDeclare("securityReview").SetClass(security.SecurityReviewLogic{}).AddPreLogic(emptyLogicSafe).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
		}.ToJsonString()).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyQuerySecurityAllPass))
	var securityPost = zagHandler.NewZagLogicDeclare("securityPost").SetClass(security_post.QuerySecurityJudgeLogic{}).AddPreLogic(redLine).AddPreLogic(securityReview)
	securityStage.AddLogics(emptyLogicSafe, redLine, securityReview, securityPost)

	//------空算子--------
	var emptyStage2 = zagHandler.NewZagStageDeclare("emptyStage2").AddPres(securityStage)
	var emptyLogic2 = zagHandler.NewZagLogicDeclare("empty2").SetClass(empty.EmptyLogic{})
	emptyStage2.AddLogics(emptyLogic2)

	//------QueryMerge阶段--------
	var stageQueryMerge = zagHandler.NewZagStageDeclare("query_merge").AddPres(securityStage)
	var QueryMerge = zagHandler.NewZagLogicDeclare("QueryMerge").SetClass(query_merge.QueryMergeLogic{})
	stageQueryMerge.AddLogics(QueryMerge)

	//------安全模块--------
	var securityStageM = zagHandler.NewZagStageDeclare("securityM").AddPres(stageQueryMerge)
	var emptyLogicSafeM = zagHandler.NewZagLogicDeclare("emptySafeM").SetClass(empty.EmptyLogic{})
	var redLineM = zagHandler.NewZagLogicDeclare("redLineM").SetClass(security.RedLineLogic{}).AddPreLogic(emptyLogicSafeM)
	var securityReviewM = zagHandler.NewZagLogicDeclare("securityReviewM").SetClass(security.SecurityReviewLogic{}).AddPreLogic(emptyLogicSafeM).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
		}.ToJsonString()).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyQueryMergeSecurityAllPass))

	var securityPostM = zagHandler.NewZagLogicDeclare("securityPostM").SetClass(security_post.QuerySecurityJudgeLogic{}).AddPreLogic(redLineM).AddPreLogic(securityReviewM)
	securityStageM.AddLogics(emptyLogicSafeM, redLineM, securityReviewM, securityPostM)

	//------空算子(安全通过)--------
	var emptyStageMOK = zagHandler.NewZagStageDeclare("emptyStageMOK").AddPres(securityStageM)
	var emptyLogicMOK = zagHandler.NewZagLogicDeclare("emptyMOK").SetClass(empty.EmptyLogic{})
	emptyStageMOK.AddLogics(emptyLogicMOK)

	//------空算子(安全通过)--------
	var emptyStageMOKAndRecall = zagHandler.NewZagStageDeclare("emptyStageMOKAndRecall").AddPres(emptyStageMOK)
	var emptyLogicMOKAndRecall = zagHandler.NewZagLogicDeclare("emptyMOKAndRecall").SetClass(empty.EmptyLogic{})
	emptyStageMOKAndRecall.AddLogics(emptyLogicMOKAndRecall)

	//------空算子(安全未通过)--------
	var emptyStageM = zagHandler.NewZagStageDeclare("emptyStageM").AddPres(securityStageM)
	var emptyLogicM = zagHandler.NewZagLogicDeclare("emptyM").SetClass(empty.EmptyLogic{})
	emptyStageM.AddLogics(emptyLogicM)

	//------recall阶段--------
	var stageKbRecall = zagHandler.NewZagStageDeclare("kbRecall").AddPres(emptyStageMOK)
	var kbZhihuRecall = zagHandler.NewZagLogicDeclare("KbZhihuRecall").SetClass(recall.KbZhihuRecallLogic{}).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), util.GetJSONIgnoreError(conf.ZSearchRecallConfig{})).
		AddConfig(conf.SummaryRecallOrderGroup.ToConvert(), "0")
	// 合并召回源
	var kbRecallSourceMerge = zagHandler.NewZagLogicDeclare("KbRecallSourceMerge").SetClass(empty.EmptyLogic{}).
		AddPreLogic(kbZhihuRecall)
	stageKbRecall.AddLogics(kbZhihuRecall, kbRecallSourceMerge)

	//------- recall MetaFetcher---------
	var recallMetaFetcherStage = zagHandler.NewZagStageDeclare("RecallMetaFetcherStage").AddPres(stageKbRecall)
	// 召回(MetaFetcher)
	var kbRecallMetaFetcher = zagHandler.NewZagLogicDeclare("kbRecallMetaFetcher").SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{})
	recallMetaFetcherStage.AddLogics(kbRecallMetaFetcher)

	// 过滤内外部召回
	var recallIoFilterStage = zagHandler.NewZagStageDeclare("RecallIoFilterStage").AddPres(recallMetaFetcherStage)
	// 内部召回过滤
	var recallInsideFilter = zagHandler.NewZagLogicDeclare("RecallInsideFilter").SetClass(recall.KbRecallIoFilterLogic{}).
		AddConfig(conf.SummaryRecallFilterIo.ToConvert(), "true")
	recallIoFilterStage.AddLogics(recallInsideFilter)

	//------- 管控过滤 filter---------
	var stageFilter = zagHandler.NewZagStageDeclare("StageFilter")
	var initFilter = zagHandler.NewZagLogicDeclare("InitFilter").SetClass(frameworkFilter.InitFilterLogic[any, any, any]{}).
		AddConfig("filterReasonMap", "filterReasonMap").AddPreLogic(recallInsideFilter)
	var validContentRegulateFetcherLogic = zagHandler.NewZagLogicDeclare("ValidContentRegulateFetcher").SetClass(meta_fetcher.ContentRegulateLogic{}).
		AddPreLogic(initFilter).AddConfig(conf.ConfigRegulateSceneCode, rpc.SceneCodeSearch).AddConfig(conf.ConfigRegulateSubSceneCode, rpc.SubSceneCodeDEFAULT)
	var contentRegulateFilterLogic = zagHandler.NewZagLogicDeclare("ContentRegulateFilter").SetClass(commonFilter.ContentRegulateFilterLogic{}).
		AddPreLogic(validContentRegulateFetcherLogic).
		AddConfig(conf.ConfigRegulateKey, rpc.VisitorCirculate)
	var postFilter = zagHandler.NewZagLogicDeclare("PostFilter").SetClass(frameworkFilter.FilterPostLogic[any, any, any]{}).
		AddConfig("filterReasonMap", "filterReasonMap").AddPreLogic(contentRegulateFilterLogic)
	stageFilter.AddLogics(initFilter, validContentRegulateFetcherLogic, contentRegulateFilterLogic, postFilter)

	//------recall handle 阶段--------
	var kbRecallHandleStage = zagHandler.NewZagStageDeclare("KbRecallHandleStage").AddPres(recallMetaFetcherStage)
	// 站内召回分块和重排序
	var kbInsideRecallChunkAndReRank = zagHandler.NewZagLogicDeclare("KbInsideRecallChunkAndReRank").SetClass(recall.KbRecallChunkAndReRankLogic{}).AddPreLogic(postFilter)
	// 召回分块内容阶段
	var kbInsideRecallChunkLimit = zagHandler.NewZagLogicDeclare("kbZhihuRecallChunkLimit").SetClass(recall.KbRecallChunkLimitLogic{}).
		AddConfig(conf.SummaryRecallSource.ToConvert(), conf.KbSourceZhihu.String()).AddPreLogic(kbInsideRecallChunkAndReRank)
	// 召回统一Merge
	var kbRecallMergeAndLimitLogic = zagHandler.NewZagLogicDeclare("kbRecallMergeAndLimitLogic").SetClass(recall.KbRecallMergeAndLimitLogic{}).AddPreLogic(kbInsideRecallChunkAndReRank).AddPreLogic(kbInsideRecallChunkLimit)
	// 转换Recall 结果为字符串
	var recallRes2ConvertString = zagHandler.NewZagLogicDeclare("RecallRes2ConvertString").SetClass(recall.KbRecallConvert2StringLogic{}).AddPreLogic(kbRecallMergeAndLimitLogic)
	kbRecallHandleStage.AddLogics(kbInsideRecallChunkAndReRank, kbInsideRecallChunkLimit, kbRecallMergeAndLimitLogic, recallRes2ConvertString)

	//------拼接Prompt阶段--------
	promptBySummary := "RULES:\n" +
		"1. 回答必须(MUST)使用中文。\n" +
		"2. 直接提供帮助即可，不要说抱歉、对不起等带有歉意的表述。\n" +
		"3. 回答不要提及“知识库”、“根据知识库”等，有类似都表达请用“据我所知”代替。\n\n" +
		"根据Knowledge完成对话：\n\n" +
		"Knowledge:\n{{.Knowledge}}\n\n" +
		"问题: {{.Query}}\n" +
		"回答:"
	var stagePrompt = zagHandler.NewZagStageDeclare("prompt")
	var buildBySummaryPrompt = zagHandler.NewZagLogicDeclare("BuildPrompt").SetClass(prompt.BuildPromptLogic{}).
		AddConfig(conf.ConfigPrompt, promptBySummary).
		AddConfig(conf.ConfigPromptID, "1002").AddPreLogic(recallRes2ConvertString).AddPreLogic(emptyLogicMOKAndRecall)

	var knowledgeEnhance = zagHandler.NewZagLogicDeclare("KnowledgeEnhance").SetClass(security.KnowledgeEnhanceLogic{}).AddPreLogic(buildBySummaryPrompt)
	stagePrompt.AddLogics(buildBySummaryPrompt, knowledgeEnhance)

	//------生成阶段--------
	var stageGenerate = zagHandler.NewZagStageDeclare("generate").AddPres(stagePrompt)
	var StreamChatLogic = zagHandler.NewZagLogicDeclare("StreamChatLogic").SetClass(generate.StreamChatLogic{}).SetTimeOut(300*1000).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.ChatConfig{
			ChatHistoryType: conf.ChatHistoryNone,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			},
		}.ToJsonString())
	var securityReviewOut = zagHandler.NewZagLogicDeclare("securityReviewOut").SetClass(security.SecurityReviewLogic{}).AddPreLogic(StreamChatLogic).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:         rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
			ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
		}.ToJsonString()).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyAnswerSecurityPass))

	stageGenerate.AddLogics(StreamChatLogic, securityReviewOut)

	//------响应阶段--------
	var stageResponse = zagHandler.NewZagStageDeclare("response").AddPres(stageGenerate, emptyStage2, emptyStageM)
	var BuildResponse = zagHandler.NewZagLogicDeclare("Response").SetClass(response.BuildResponseLogic{}).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyRelevantQueries, graph_macro.ZagKeyCurrentAnswer))
	var SaveDialog = zagHandler.NewZagLogicDeclare("SaveDialog").SetClass(consumer.SaveDialogRecordLogic{}).AddPreLogic(BuildResponse).
		AddConfig(conf.ConfigInputNames, util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyCurrentAnswer))

	stageResponse.AddLogics(BuildResponse, SaveDialog)

	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {QueryMerge.Name},
		entities.Break:  {emptyLogic2.Name},
	})

	securityPostM.SetSelectEdge(map[string][]string{
		entities.Normal: {emptyLogicMOK.Name},
		entities.Break:  {emptyLogicM.Name},
	})

	//把base算子、流程声明 加载到图中
	zagGraph.AddStagesWithLogics(stageRoot, stagePrepare, emptyStage1, securityStage, emptyStage2, stageQueryMerge, emptyStageMOK, emptyStageMOKAndRecall, securityStageM, emptyStageM,
		stageKbRecall, recallMetaFetcherStage, recallIoFilterStage, stageFilter, kbRecallHandleStage, stagePrompt, stageGenerate, stageResponse)

	//-------api 声明 >> 业务逻辑图-------
	return zagHandler.ApiDeclare2Graph[C, U, I](zagGraph)
}

```

- 王瞎扯
```
package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/consumer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

func StreamChatAiTabXCGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("chat_graph", entities.ApiStreamChat+"."+proto.ChatType_AI_TAB_XC.String(), "1.1")

	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare("root")
	var copyUserMeta = zagHandler.NewZagLogicDeclare("CopyUserMeta").SetClass(root.CopyUserMetaLogic{}).
		AddConfig(conf.ConfigApi, entities.ApiStreamChat).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyQueryText,
			graph_macro.ZagKeyMemberId, graph_macro.ZagKeyScene, graph_macro.ZagKeySessionId))

	var UserMessage = zagHandler.NewZagLogicDeclare("UserMessage").SetClass(root.UserMessageLogic{}).SetStore(conf.SourceQueryItemLogicStoreKey.String()).
		AddPreLogic(copyUserMeta)

	stageRoot.AddLogics(copyUserMeta, UserMessage)

	//------prepare阶段--------
	var stagePrepare = zagHandler.NewZagStageDeclare("prepare").AddPres(stageRoot)
	var ChatHistory = zagHandler.NewZagLogicDeclare("ChatHistory").SetClass(root.ChatHistoryLogic{})
	stagePrepare.AddLogics(ChatHistory)

	//------空算子--------
	var emptyStage1 = zagHandler.NewZagStageDeclare("emptyStage1").AddPres(stageRoot)
	var emptyLogic1 = zagHandler.NewZagLogicDeclare("empty1").SetClass(empty.EmptyLogic{})
	emptyStage1.AddLogics(emptyLogic1)

	//------安全模块--------
	var securityStage = zagHandler.NewZagStageDeclare("security").AddPres(emptyStage1, stagePrepare)
	var emptyLogicSafe = zagHandler.NewZagLogicDeclare("emptySafe").SetClass(empty.EmptyLogic{})
	var redLine = zagHandler.NewZagLogicDeclare("redLine").SetClass(security.RedLineLogic{}).AddPreLogic(emptyLogicSafe)
	//var faq = zagHandler.NewZagLogicDeclare("FAQ").SetClass(security.FAQLogic{}).AddPreLogic(emptyLogicSafe)
	var securityReview = zagHandler.NewZagLogicDeclare("securityReview").SetClass(security.SecurityReviewLogic{}).AddPreLogic(emptyLogicSafe).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceAiQuery.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
		}.ToJsonString())
	var securityPost = zagHandler.NewZagLogicDeclare("securityPost").SetClass(security_post.QuerySecurityJudgeLogic{}).AddPreLogic(redLine).AddPreLogic(securityReview)
	securityStage.AddLogics(emptyLogicSafe, redLine, securityReview, securityPost)

	//------空算子--------
	var emptyStage2 = zagHandler.NewZagStageDeclare("emptyStage").AddPres(securityStage)
	var emptyLogic2 = zagHandler.NewZagLogicDeclare("empty").SetClass(empty.EmptyLogic{})
	emptyStage2.AddLogics(emptyLogic2)

	//------拼接Prompt阶段--------
	var stagePrompt = zagHandler.NewZagStageDeclare("prompt").AddPres(securityStage)
	var BuildPrompt = zagHandler.NewZagLogicDeclare("BuildPrompt").SetClass(prompt.BuildPromptLogic{}).AddConfig(conf.ConfigPrompt, "{{.Query}}").AddConfig(conf.ConfigPromptID, "1001")
	var KnowledgeEnhance = zagHandler.NewZagLogicDeclare("KnowledgeEnhance").SetClass(security.KnowledgeEnhanceLogic{}).AddPreLogic(BuildPrompt)
	stagePrompt.AddLogics(BuildPrompt, KnowledgeEnhance)

	//------生成阶段--------
	var stageGenerate = zagHandler.NewZagStageDeclare("generate").AddPres(stagePrompt)
	var StreamChatLogic = zagHandler.NewZagLogicDeclare("StreamChatLogic").SetClass(generate.StreamChatLogic{}).SetTimeOut(300*1000).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.ChatConfig{
			ModelName:       entities.WangXiaChe8B,
			AIProfile:       "\n现在请你扮演王瞎扯和我进行对话。\n\n# 王瞎扯基本信息\n王瞎扯擅长抖机灵，他从不正面回答问题，而是回避问题本身，给出看似一针见血的答案，以另辟蹊径的角度创造回答。\n\n# 王瞎扯的性格:\n喜欢瞎扯、抖机灵\n\n# 人物关系\n接下来的对话里，你需要扮演王瞎扯\n\n\n\n* 现在请你假扮王瞎扯与我进行对话；\n[开始对话]\n",
			TrimPrefix:      "王瞎扯：",
			ChatHistoryType: conf.ChatHistoryStrLengthLimit,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceAiAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			},
		}.ToJsonString())
	var securityReviewOut = zagHandler.NewZagLogicDeclare("securityReviewOut").SetClass(security.SecurityReviewLogic{}).AddPreLogic(StreamChatLogic).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:         rpc.RiskCheckSourceAiAnswer.ToConvert(),
			ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
			ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
		}.ToJsonString())
	stageGenerate.AddLogics(StreamChatLogic, securityReviewOut)

	//------响应阶段--------
	var stageResponse = zagHandler.NewZagStageDeclare("response").AddPres(stageGenerate, emptyStage2)
	var BuildResponse = zagHandler.NewZagLogicDeclare("Response").SetClass(response.BuildResponseLogic{}).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyRelevantQueries, graph_macro.ZagKeyCurrentAnswer))
	var SaveDialog = zagHandler.NewZagLogicDeclare("SaveDialog").SetClass(consumer.SaveDialogRecordLogic{}).AddPreLogic(BuildResponse).
		AddConfig(conf.ConfigInputNames, util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyCurrentAnswer))

	stageResponse.AddLogics(BuildResponse, SaveDialog)

	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {BuildPrompt.Name},
		entities.Break:  {emptyLogic2.Name},
	})

	//把base算子、流程声明 加载到图中
	zagGraph.AddStagesWithLogics(stageRoot, emptyStage1, securityStage, stagePrepare, emptyStage2, stagePrompt, stageGenerate, stageResponse)

	//-------api 声明 >> 业务逻辑图-------
	return zagHandler.ApiDeclare2Graph[C, U, I](zagGraph)
}

```

- 知问快答
```
package api

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/consumer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

func StreamChatAiTabZWKDGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("chat_graph", entities.ApiStreamChat+"."+proto.ChatType_AI_TAB_ZWKD.String(), "1.1")

	//================流程声明================
	//------执行入口路由--------
	var stageRoot = zagHandler.NewZagStageDeclare("root")
	var copyUserMeta = zagHandler.NewZagLogicDeclare("CopyUserMeta").SetClass(root.CopyUserMetaLogic{}).
		AddConfig(conf.ConfigApi, entities.ApiStreamChat).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyQueryText,
			graph_macro.ZagKeyMemberId, graph_macro.ZagKeyScene, graph_macro.ZagKeySessionId))

	var UserMessage = zagHandler.NewZagLogicDeclare("UserMessage").SetClass(root.UserMessageLogic{}).SetStore(conf.SourceQueryItemLogicStoreKey.String()).
		AddPreLogic(copyUserMeta)

	stageRoot.AddLogics(copyUserMeta, UserMessage)

	//------prepare阶段--------
	var stagePrepare = zagHandler.NewZagStageDeclare("prepare").AddPres(stageRoot)
	var ChatHistory = zagHandler.NewZagLogicDeclare("ChatHistory").SetClass(root.ChatHistoryLogic{})
	stagePrepare.AddLogics(ChatHistory)

	//------空算子--------
	var emptyStage1 = zagHandler.NewZagStageDeclare("emptyStage1").AddPres(stageRoot)
	var emptyLogic1 = zagHandler.NewZagLogicDeclare("empty1").SetClass(empty.EmptyLogic{})
	emptyStage1.AddLogics(emptyLogic1)

	//------安全模块--------
	var securityStage = zagHandler.NewZagStageDeclare("security").AddPres(emptyStage1, stagePrepare)
	var emptyLogicSafe = zagHandler.NewZagLogicDeclare("emptySafe").SetClass(empty.EmptyLogic{})
	var redLine = zagHandler.NewZagLogicDeclare("redLine").SetClass(security.RedLineLogic{}).AddPreLogic(emptyLogicSafe)
	//var faq = zagHandler.NewZagLogicDeclare("FAQ").SetClass(security.FAQLogic{}).AddPreLogic(emptyLogicSafe)
	var securityReview = zagHandler.NewZagLogicDeclare("securityReview").SetClass(security.SecurityReviewLogic{}).AddPreLogic(emptyLogicSafe).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceAiQuery.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
		}.ToJsonString())
	var securityPost = zagHandler.NewZagLogicDeclare("securityPost").SetClass(security_post.QuerySecurityJudgeLogic{}).AddPreLogic(redLine).AddPreLogic(securityReview)
	securityStage.AddLogics(emptyLogicSafe, redLine, securityReview, securityPost)

	//------空算子--------
	var emptyStage2 = zagHandler.NewZagStageDeclare("emptyStage").AddPres(securityStage)
	var emptyLogic2 = zagHandler.NewZagLogicDeclare("empty").SetClass(empty.EmptyLogic{})
	emptyStage2.AddLogics(emptyLogic2)

	//------拼接Prompt阶段--------
	var stagePrompt = zagHandler.NewZagStageDeclare("prompt").AddPres(securityStage)
	var BuildPrompt = zagHandler.NewZagLogicDeclare("BuildPrompt").SetClass(prompt.BuildPromptLogic{}).AddConfig(conf.ConfigPrompt, "{{.Query}}").AddConfig(conf.ConfigPromptID, "1001")
	var KnowledgeEnhance = zagHandler.NewZagLogicDeclare("KnowledgeEnhance").SetClass(security.KnowledgeEnhanceLogic{}).AddPreLogic(BuildPrompt)
	stagePrompt.AddLogics(BuildPrompt, KnowledgeEnhance)

	//------生成阶段--------
	var stageGenerate = zagHandler.NewZagStageDeclare("generate").AddPres(stagePrompt)
	var StreamChatLogic = zagHandler.NewZagLogicDeclare("StreamChatLogic").SetClass(generate.StreamChatLogic{}).SetTimeOut(300*1000).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.ChatConfig{
			ModelName:       entities.ZhiWenKuaiDa8B,
			AIProfile:       "\n现在请你扮演知问快答和我进行对话\n\n#知问快答基本信息\n知问快答总是渴望与用户分享有趣的小知识和趣闻，对话时通过分享奇特的小知识吸引用户，激发他们的好奇心，引导用户继续对话。\n\n#知问快答的性格\n博学、循循善诱、乐于分享、乐于助人、热心、智慧、耐心、富有洞察力、鼓舞人心、亲切、可靠、深思熟虑、具有启发性、谨慎\n\n#人物关系\n接下来的对话里，你需要扮演知问快答，我将扮演用户。\n首先，知问快答需要鼓励用户提出问题，如“有什么特别的冷知识？”，其次，用户需要提出问题，然后，知问快答需要回应用户提出的有趣事实或知识。如此往复，重复对话，以引人入胜和对话式的语调传达简短答案，使互动既愉快又有教育意义。\n我们的关系是：知问快答主动引导用户提问并解答，满足用户的好奇心和求知欲。\n\n#知问快答的语言风格\n知识分享: 能够以回答形式提供有趣的事实和知识。\n互动引导: 通过提问和保持对话式语调来鼓励用户互动。\n语言流利: 中文流利，风格既信息丰富又娱乐性强。\n长度限制：提供简短回答，字数不可以超过300中文字符。\n\n\n#相关人物\n##知问快答\n循循善诱的知识分享者\n##用户\n有求知欲，对知问快答进行对话，提出问题或表达诉求。\n\n*现在请你扮演知问快答与我进行对话\n\n*我将扮演：用户\n\n*我们的关系是：知问快答擅长用300字内，切中问题要害，解释用户提出的疑问，以引人入胜和对话式的语调传达简短答案，使互动既愉快又有教育意义。\n\n[开始对话]",
			TrimPrefix:      "知问快答：",
			ChatHistoryType: conf.ChatHistoryStrLengthLimit,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceAiAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			},
		}.ToJsonString())
	var securityReviewOut = zagHandler.NewZagLogicDeclare("securityReviewOut").SetClass(security.SecurityReviewLogic{}).AddPreLogic(StreamChatLogic).
		AddConfig(conf.JsonConfigLogicKey.ToConvert(), conf.SecurityConfig{
			SourceId:         rpc.RiskCheckSourceAiAnswer.ToConvert(),
			ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
			ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
		}.ToJsonString())
	stageGenerate.AddLogics(StreamChatLogic, securityReviewOut)

	//------响应阶段--------
	var stageResponse = zagHandler.NewZagStageDeclare("response").AddPres(stageGenerate, emptyStage2)
	var BuildResponse = zagHandler.NewZagLogicDeclare("Response").SetClass(response.BuildResponseLogic{}).
		AddConfig(conf.ConfigOutputNames, util2.JoinNamesToString(graph_macro.ZagKeyRelevantQueries, graph_macro.ZagKeyCurrentAnswer))
	var SaveDialog = zagHandler.NewZagLogicDeclare("SaveDialog").SetClass(consumer.SaveDialogRecordLogic{}).AddPreLogic(BuildResponse).
		AddConfig(conf.ConfigInputNames, util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyCurrentAnswer))

	stageResponse.AddLogics(BuildResponse, SaveDialog)

	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {BuildPrompt.Name},
		entities.Break:  {emptyLogic2.Name},
	})

	//把base算子、流程声明 加载到图中
	zagGraph.AddStagesWithLogics(stageRoot, emptyStage1, securityStage, stagePrepare, emptyStage2, stagePrompt, stageGenerate, stageResponse)

	//-------api 声明 >> 业务逻辑图-------
	return zagHandler.ApiDeclare2Graph[C, U, I](zagGraph)
}


```