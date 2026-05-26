package graph

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/conf/digital_author_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/filter"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/finalizer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/intention"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/prepare"
	digitalAuthorPrompt "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/recall_merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/response"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/logic/task"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	conf2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/query_merge"
	commonFilter "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/filter"
	commonRecall "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	frameworkFilter "git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/graph"
)

func DigitalAuthorGraph[C, U, I any]() *graph.Graph {
	//========图声明========
	var zagGraph = zagHandler.NewZagGraphDeclare("digital_author_graph", graph_constant.ApiDigitalAuthorChat+"."+proto.ChatType_DIGITAL_AUTHOR.String(), "1.2")

	//================流程声明================
	//------执行入口路由--------
	var stagePrepare = zagHandler.NewZagStageDeclare(digital_author_conf.PrepareStage)
	//------prepare阶段--------
	var userMessageStage = zagHandler.NewZagStageDeclare(digital_author_conf.UserMessageStage).AddPres(stagePrepare)
	//------安全模块--------
	var securityStage = zagHandler.NewZagStageDeclare(digital_author_conf.SecurityStage).AddPres(userMessageStage)
	//------空算子--------
	var emptyStage1 = zagHandler.NewZagStageDeclare(digital_author_conf.EmptyStage1Stage).AddPres(securityStage)
	//------query merge--------
	var queryMergeStage = zagHandler.NewZagStageDeclare(digital_author_conf.QueryMergeStage).AddPres(securityStage)
	//------意图识别--------
	var intentionStage = zagHandler.NewZagStageDeclare(digital_author_conf.IntentionStage).AddPres(queryMergeStage)
	//------任务识别--------
	var taskStage = zagHandler.NewZagStageDeclare(digital_author_conf.TaskStage).AddPres(queryMergeStage)
	//------空算子--------
	var emptyStage2 = zagHandler.NewZagStageDeclare(digital_author_conf.EmptyStage2Stage)
	//------安全阶段--------
	var securityReviewStage = zagHandler.NewZagStageDeclare(digital_author_conf.SecurityReviewStage)
	//------meta fetcher--------
	var metaFetcherStage = zagHandler.NewZagStageDeclare(digital_author_conf.MetaFetcherStage)
	//------索引召回--------
	var recallStage = zagHandler.NewZagStageDeclare(digital_author_conf.RecallStage)
	//------索引meta fetch--------
	var recallMetaFetcherStage = zagHandler.NewZagStageDeclare(digital_author_conf.RecallMetaFetcherStage)
	//------索引filter--------
	var recallFilterStage = zagHandler.NewZagStageDeclare(digital_author_conf.RecallFilterStage)
	//-------索引 merge-------
	var recallMergeStage = zagHandler.NewZagStageDeclare(digital_author_conf.RecallMergeStage).AddPres(recallStage, recallMetaFetcherStage, recallFilterStage)
	//------prompt拼接--------
	var promptStage = zagHandler.NewZagStageDeclare(digital_author_conf.PromptStage)
	//------生成阶段--------
	var generateStage = zagHandler.NewZagStageDeclare(digital_author_conf.GenerateStage)
	//------summary阶段--------
	var summaryStage = zagHandler.NewZagStageDeclare(digital_author_conf.SummaryStage)
	//------响应阶段--------
	var responseStage = zagHandler.NewZagStageDeclare(digital_author_conf.ResponseStage).AddPres(emptyStage1, summaryStage)
	//------logger阶段--------
	var finalizerStage = zagHandler.NewZagStageDeclare(digital_author_conf.FinalizerStage).AddPres(responseStage)

	//================算子声明================
	//-------request算子-------
	var userMessage = zagHandler.NewZagLogicDeclare(digital_author_conf.UserMessageLogic).SetClass(root.UserMessageLogic{}).SetStore(conf2.SourceQueryItemLogicStoreKey.String())
	//-------安全模块算子-------
	var redLine = zagHandler.NewZagLogicDeclare(digital_author_conf.RedLineLogic).SetClass(security.RedLineLogic{})
	var faq = zagHandler.NewZagLogicDeclare(digital_author_conf.FAQLogic).SetClass(security.FAQLogic{})
	var securityPost = zagHandler.NewZagLogicDeclare(digital_author_conf.SecurityPostLogic).SetClass(security_post.StaticQAJudgeLogic{}).AddPreLogic(redLine).AddPreLogic(faq)
	//-------prepare算子-------
	var chatHistory = zagHandler.NewZagLogicDeclare(digital_author_conf.DigitalAuthorChatHistoryLogic).SetClass(prepare.DigitalAuthorChatHistoryLogic{})
	var authorMeta = zagHandler.NewZagLogicDeclare(digital_author_conf.AuthorMetaLogic).SetClass(prepare.AuthorMetaLogic{})
	//-------query merge-------
	var queryMergeLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryMergeLogic).SetClass(query_merge.QueryMergeLogic{})
	//------意图识别判断--------
	var taskFetcherLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.TaskFetcherLogic).SetClass(task.TaskFetcherLogic{})
	var task2SummaryJudgeLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.Task2SummaryJudgeLogic).SetClass(intention.Task2SummaryJudgeLogic{}).
		AddPreLogic(taskFetcherLogic)

	var intentionPromptLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.IntentionPromptLogic).SetClass(prompt.BuildPromptLogic{}).
		AddPreLogic(queryMergeLogic)
	var intentionSystemPromptLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.IntentionSystemPromptLogic).SetClass(prompt.BuildPromptLogic{}).
		AddPreLogic(queryMergeLogic)
	var intentionChatLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.IntentionChatLogic).SetClass(generate.ChatLogic{}).SetTimeOut(300 * 1000).
		AddPreLogic(intentionPromptLogic).
		AddPreLogic(intentionSystemPromptLogic)
	var intentionJudgeLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.IntentionJudgeLogic).SetClass(intention.IntentionJudgeLogic{}).
		AddPreLogic(intentionChatLogic)

	//------安全审核接口--------
	var queryInDomainSecurityReviewLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryInDomainSecurityReviewLogic).SetClass(security.SecurityReviewLogic{}).
		AddPreLogic(intentionJudgeLogic)
	var queryInDomainSecurityPostLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryInDomainSecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(queryInDomainSecurityReviewLogic)
	//-------空算子-------
	var emptyLogic1 = zagHandler.NewZagLogicDeclare(digital_author_conf.Empty1Logic).SetClass(empty.EmptyLogic{})
	//------meta fetcher--------
	var klaraEmbeddingFetcherLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.KlaraEmbeddingFetcherLogic).SetClass(meta_fetcher.KlaraEmbeddingFetcherLogic{}).AddPreLogic(queryInDomainSecurityPostLogic)
	var unifiedEmbeddingFetcherLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.UnifiedEmbeddingFetcherLogic).SetClass(meta_fetcher.UnifiedEmbeddingFetcherLogic{}).AddPreLogic(queryInDomainSecurityPostLogic)
	var quKeywordFetcherLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QuKeywordFetcherLogic).SetClass(meta_fetcher.QuKeywordFetcherLogic{}).AddPreLogic(queryInDomainSecurityPostLogic)
	//-------召回算子-------
	var rumP0CustomRecallLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.RumP0CustomRecallLogic).SetClass(commonRecall.RumRecallLogic{}).
		AddPreLogic(klaraEmbeddingFetcherLogic)

	var rumP1ZhihuRecallLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.RumP1ZhihuRecallLogic).SetClass(commonRecall.RumRecallLogic{}).
		AddPreLogic(unifiedEmbeddingFetcherLogic)

	var rumP2ZhihuRecallLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.RumP2ZhihuRecallLogic).SetClass(commonRecall.RumRecallLogic{}).
		AddPreLogic(unifiedEmbeddingFetcherLogic)

	var rumP2LawRecallLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.RumP2LawRecallLogic).SetClass(commonRecall.RumRecallLogic{}).
		AddPreLogic(klaraEmbeddingFetcherLogic)

	var ruceneP0CustomRecallLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.RuceneP0CustomRecallLogic).SetClass(commonRecall.RuceneLogic{}).
		AddPreLogic(quKeywordFetcherLogic)

	var ruceneP2LawRecallLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.RuceneP2LawRecallLogic).SetClass(commonRecall.RuceneLogic{}).
		AddPreLogic(quKeywordFetcherLogic)

	var zsearchP1RecallLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.ZsearchP1ZhihuRecallLogic).SetClass(commonRecall.KbZhihuRecallLogic{}).
		AddPreLogic(queryInDomainSecurityPostLogic)

	var zsearchP2RecallLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.ZsearchP2ZhihuRecallLogic).SetClass(commonRecall.KbZhihuRecallLogic{}).
		AddPreLogic(queryInDomainSecurityPostLogic)

	//------recall meta fetcher--------
	var initFilter = zagHandler.NewZagLogicDeclare(digital_author_conf.InitFilterLogic).SetClass(frameworkFilter.InitFilterLogic[any, any, any]{}).
		AddConfig("filterReasonMap", "filterReasonMap").AddPreLogic(zsearchP1RecallLogic)
	var contentCoreMetaFetcher1Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.ContentCoreMetaFetcher1Logic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).
		AddPreLogic(rumP1ZhihuRecallLogic)
	var contentCoreMetaFetcher2Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.ContentCoreMetaFetcher2Logic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).
		AddPreLogic(rumP2ZhihuRecallLogic)
	var contentCoreMetaFetcher3Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.ContentCoreMetaFetcher3Logic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).
		AddPreLogic(initFilter)
	var contentCoreMetaFetcher4Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.ContentCoreMetaFetcher4Logic).SetClass(meta_fetcher.ContentCoreMetaFetcherLogic{}).
		AddPreLogic(zsearchP2RecallLogic)
	var parentContentCoreMetaFetcher1Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.ParentContentCoreMetaFetcher1Logic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).
		AddPreLogic(contentCoreMetaFetcher1Logic)
	var parentContentCoreMetaFetcher2Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.ParentContentCoreMetaFetcher2Logic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).
		AddPreLogic(contentCoreMetaFetcher2Logic)
	var parentContentCoreMetaFetcher3Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.ParentContentCoreMetaFetcher3Logic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).
		AddPreLogic(contentCoreMetaFetcher3Logic)
	var parentContentCoreMetaFetcher4Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.ParentContentCoreMetaFetcher4Logic).SetClass(meta_fetcher.ParentContentCoreMetaFetcherLogic{}).
		AddPreLogic(contentCoreMetaFetcher4Logic)

	var commercialContentRegulateFetcherLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.CommercialContentRegulateFetcherLogic).SetClass(meta_fetcher.ContentRegulateLogic{}).
		AddPreLogic(initFilter)
	//------recall filter--------
	var indexDeleteFilterLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.IndexDeleteFilterLogic).SetClass(filter.IndexDeleteFilterLogic{}).
		AddPreLogic(initFilter)
	var contentRegulateFilterLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.ContentRegulateFilterLogic).SetClass(commonFilter.ContentRegulateFilterLogic{}).
		AddPreLogic(initFilter).
		AddPreLogic(commercialContentRegulateFetcherLogic)
	var postFilter = zagHandler.NewZagLogicDeclare(digital_author_conf.PostFilterLogic).SetClass(frameworkFilter.FilterPostLogic[any, any, any]{}).
		AddConfig("filterReasonMap", "filterReasonMap").AddPreLogic(indexDeleteFilterLogic).AddPreLogic(contentRegulateFilterLogic).AddPreLogic(contentCoreMetaFetcher3Logic)

	//------recall merge ----------
	var emptyLogic3 = zagHandler.NewZagLogicDeclare(digital_author_conf.Empty3Logic).SetClass(empty.EmptyLogic{}).AddPreLogic(intentionJudgeLogic)
	var recallMergeLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.RecallMergeLogic).SetClass(recall_merge.RecallMergeLogic{})
	var getQueryMergeLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.GetQueryMergeLogic).SetClass(query_merge.GetQueryMergeLogic{}).AddPreLogic(recallMergeLogic).AddPreLogic(emptyLogic3)
	var queryEmptyRecallSecurityReviewLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryEmptyRecallSecurityReviewLogic).SetClass(security.SecurityReviewLogic{}).
		AddPreLogic(getQueryMergeLogic)
	var queryEmptyRecallSecurityPostLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryEmptyRecallSecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(queryEmptyRecallSecurityReviewLogic)
	var emptyLogic2 = zagHandler.NewZagLogicDeclare(digital_author_conf.Empty2Logic).SetClass(empty.EmptyLogic{}).AddPreLogic(queryInDomainSecurityPostLogic).AddPreLogic(queryEmptyRecallSecurityPostLogic)

	var alreadyIntentionJudgeLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.AlreadyIntentionJudgeLogic).SetClass(intention.AlreadyIntentionJudgeLogic{}).
		AddPreLogic(queryEmptyRecallSecurityPostLogic)
	var queryPromptLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryPromptLogic).SetClass(digitalAuthorPrompt.BuildDigitalAuthorPromptLogic{}).AddPreLogic(recallMergeLogic)
	var queryPromptSmallTalkLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryPromptSmallTalkLogic).SetClass(digitalAuthorPrompt.BuildDigitalAuthorPromptLogic{}).AddPreLogic(alreadyIntentionJudgeLogic)
	var queryPromptEmptyRecallLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryPromptEmptyRecallLogic).SetClass(digitalAuthorPrompt.BuildDigitalAuthorPromptLogic{}).AddPreLogic(alreadyIntentionJudgeLogic)
	var queryKnowledgeEnhanceLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryKnowledgeEnhanceLogic).SetClass(security.KnowledgeEnhanceLogic{}).AddPreLogic(queryPromptLogic)
	var queryKnowledgeEnhance2Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryKnowledgeEnhance2Logic).SetClass(security.KnowledgeEnhanceLogic{}).AddPreLogic(queryPromptSmallTalkLogic)
	var queryKnowledgeEnhance3Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.QueryKnowledgeEnhance3Logic).SetClass(security.KnowledgeEnhanceLogic{}).AddPreLogic(queryPromptEmptyRecallLogic)

	var systemPromptLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.SystemPromptLogic).SetClass(prompt.BuildPromptLogic{}).
		AddPreLogic(recallMergeLogic)
	var systemPrompt2Logic = zagHandler.NewZagLogicDeclare(digital_author_conf.SystemPrompt2Logic).SetClass(prompt.BuildPromptLogic{}).
		AddPreLogic(queryEmptyRecallSecurityPostLogic)

	//-------生成算子-------
	var inDomainChatLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.InDomainChatLogic).SetClass(generate.ChatLogic{}).
		AddPreLogic(queryKnowledgeEnhanceLogic).AddPreLogic(systemPromptLogic)
	var smallTalkChatLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.SmallTalkChatLogic).SetClass(generate.ChatLogic{}).
		AddPreLogic(queryKnowledgeEnhance2Logic).AddPreLogic(queryKnowledgeEnhance3Logic).AddPreLogic(systemPrompt2Logic)
	var summary = zagHandler.NewZagLogicDeclare(digital_author_conf.SummaryLogic).SetClass(mapping.MultiChatSummaryLogic{}).AddPreLogic(task2SummaryJudgeLogic)
	//------安全审核接口--------
	var answerInDomainSecurityReviewLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.AnswerInDomainSecurityReviewLogic).SetClass(security.SecurityReviewLogic{}).
		AddPreLogic(inDomainChatLogic)
	var answerEmptyRecallSecurityReviewLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.AnswerSmallTalkSecurityReviewLogic).SetClass(security.SecurityReviewLogic{}).
		AddPreLogic(smallTalkChatLogic)
	var answerInDomainSecurityPostLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.AnswerInDomainSecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(answerInDomainSecurityReviewLogic)
	var answerEmptyRecallSecurityPostLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.AnswerSmallTalkSecurityPostLogic).SetClass(security_post.QuerySecurityJudgeLogic{}).
		AddPreLogic(answerEmptyRecallSecurityReviewLogic)
	//-------响应算子-------
	var buildResponse = zagHandler.NewZagLogicDeclare(digital_author_conf.ResponseLogic).SetClass(response.DigitalAuthorBuildResponseLogic{}).AddPreLogic(emptyLogic2).AddPreLogic(answerInDomainSecurityPostLogic).AddPreLogic(answerEmptyRecallSecurityPostLogic)
	// -------日志记录-------
	var internalTracingRecordLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.InternalTracingRecordLogic).SetClass(finalizer.InternalTracingRecordLogic{})
	var externalTracingRecordLogic = zagHandler.NewZagLogicDeclare(digital_author_conf.ExternalTracingRecordLogic).SetClass(finalizer.ExternalTracingRecordLogic{})

	//================条件依赖===================
	securityPost.SetSelectEdge(map[string][]string{
		entities.Normal: {queryMergeLogic.Name},
		entities.Break:  {emptyLogic1.Name},
	})
	intentionJudgeLogic.SetSelectEdge(map[string][]string{
		proto.IntentionType_AMBIGUOUS.String():           {emptyLogic3.Name},
		proto.IntentionType_NO_SEARCH_INTENTION.String(): {emptyLogic3.Name},
		proto.IntentionType_SEARCH_INTENTION.String():    {queryInDomainSecurityReviewLogic.Name},
	})
	queryInDomainSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {klaraEmbeddingFetcherLogic.Name, unifiedEmbeddingFetcherLogic.Name, quKeywordFetcherLogic.Name, zsearchP1RecallLogic.Name, zsearchP2RecallLogic.Name},
		entities.Break:  {emptyLogic2.Name},
	})
	queryEmptyRecallSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {alreadyIntentionJudgeLogic.Name, systemPrompt2Logic.Name},
		entities.Break:  {emptyLogic2.Name},
	})
	alreadyIntentionJudgeLogic.SetSelectEdge(map[string][]string{
		proto.IntentionType_AMBIGUOUS.String():           {queryPromptSmallTalkLogic.Name},
		proto.IntentionType_NO_SEARCH_INTENTION.String(): {queryPromptSmallTalkLogic.Name},
		proto.IntentionType_SEARCH_INTENTION.String():    {queryPromptEmptyRecallLogic.Name},
	})
	recallMergeLogic.SetSelectEdge(map[string][]string{
		entities.HasRetrieval:   {queryPromptLogic.Name, systemPromptLogic.Name},
		entities.EmptyRetrieval: {getQueryMergeLogic.Name},
	})
	task2SummaryJudgeLogic.SetSelectEdge(map[string][]string{
		entities.NeedSummary: {summary.Name},
	})
	answerEmptyRecallSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {buildResponse.Name},
		entities.Break:  {buildResponse.Name},
	})
	answerInDomainSecurityPostLogic.SetSelectEdge(map[string][]string{
		entities.Normal: {buildResponse.Name},
		entities.Break:  {buildResponse.Name},
	})

	//================流程添加算子================
	stagePrepare.AddLogics(chatHistory, authorMeta)
	userMessageStage.AddLogics(userMessage)
	securityStage.AddLogics(redLine, faq, securityPost)
	queryMergeStage.AddLogics(queryMergeLogic)
	intentionStage.AddLogics(intentionPromptLogic, intentionSystemPromptLogic, intentionChatLogic, intentionJudgeLogic)
	taskStage.AddLogics(taskFetcherLogic, task2SummaryJudgeLogic)
	metaFetcherStage.AddLogics(klaraEmbeddingFetcherLogic, unifiedEmbeddingFetcherLogic, quKeywordFetcherLogic)
	recallStage.AddLogics(rumP0CustomRecallLogic, rumP1ZhihuRecallLogic, rumP2ZhihuRecallLogic, rumP2LawRecallLogic, ruceneP0CustomRecallLogic, ruceneP2LawRecallLogic, zsearchP1RecallLogic, zsearchP2RecallLogic)
	recallFilterStage.AddLogics(initFilter, indexDeleteFilterLogic, contentRegulateFilterLogic, postFilter)
	recallMetaFetcherStage.AddLogics(contentCoreMetaFetcher1Logic, contentCoreMetaFetcher2Logic, contentCoreMetaFetcher3Logic, contentCoreMetaFetcher4Logic, commercialContentRegulateFetcherLogic,
		parentContentCoreMetaFetcher1Logic, parentContentCoreMetaFetcher2Logic, parentContentCoreMetaFetcher3Logic, parentContentCoreMetaFetcher4Logic)
	recallMergeStage.AddLogics(recallMergeLogic)
	emptyStage1.AddLogics(emptyLogic1)
	emptyStage2.AddLogics(emptyLogic2, emptyLogic3, getQueryMergeLogic)
	promptStage.AddLogics(queryPromptLogic, alreadyIntentionJudgeLogic, queryPromptSmallTalkLogic, queryPromptEmptyRecallLogic, systemPromptLogic, systemPrompt2Logic, queryKnowledgeEnhanceLogic, queryKnowledgeEnhance2Logic, queryKnowledgeEnhance3Logic)
	generateStage.AddLogics(inDomainChatLogic, smallTalkChatLogic)
	securityReviewStage.AddLogics(queryInDomainSecurityReviewLogic, queryEmptyRecallSecurityReviewLogic, queryInDomainSecurityPostLogic, queryEmptyRecallSecurityPostLogic,
		answerInDomainSecurityReviewLogic, answerEmptyRecallSecurityReviewLogic, answerInDomainSecurityPostLogic, answerEmptyRecallSecurityPostLogic)
	summaryStage.AddLogics(summary)
	responseStage.AddLogics(buildResponse)
	finalizerStage.AddLogics(internalTracingRecordLogic, externalTracingRecordLogic)

	stages := []*zagHandler.DeclareStage{
		stagePrepare,
		userMessageStage,
		securityStage,
		queryMergeStage,
		intentionStage,
		taskStage,
		metaFetcherStage,
		recallStage,
		recallFilterStage,
		recallMetaFetcherStage,
		recallMergeStage,
		emptyStage1,
		emptyStage2,
		promptStage,
		generateStage,
		securityReviewStage,
		summaryStage,
		responseStage,
		finalizerStage,
	}

	// 为算子添加 config
	for _, stage := range stages {
		for _, logic := range stage.LogicsPre {
			logic.AddConfigs(digital_author_conf.LogicStaticConfigMap[logic.Name])
		}
	}

	//把base算子、流程声明 加载到图中
	zagGraph.AddStagesWithLogics(stages...)

	//-------api 声明 >> 业务逻辑图-------
	return zagHandler.ApiDeclare2Graph[C, U, I](zagGraph)
}
