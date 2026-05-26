package resources

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/chat_cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/choose"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/condition"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/consumer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/empty"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/mapping"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/meta_fetcher"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/query_merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/response"
	recallFilter "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/filter"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/merge"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/recall"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/root"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security_post"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/sub_graph/root_logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/sub_graph/sub_logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	frameworkFilter "git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/logic_store"
)

var sceneName = graph_constant.ApiStreamChat

var initOnce = util.Make(func() interface{} {
	log.Infof(context.Background(), "PutLogic start")
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.CopyUserMetaLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewCopyUserMetaLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.UserMessageLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewUserMessageLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.RecallQueryLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewRecallQueryLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.ChatHistoryLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewChatHistoryLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.SessionInfoLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewSessionInfoLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.KnowledgeBaseInfoLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewKnowledgeBaseInfoLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.MembersInfoLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewMembersInfoLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&query_merge.QueryMergeLogic{}, func(name string, config map[string]string) interface{} {
		return query_merge.NewQueryMergeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&query_merge.GetQueryMergeLogic{}, func(name string, config map[string]string) interface{} {
		return query_merge.NewGetQueryMergeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.QueryRouterLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewQueryRouterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&prompt.BuildPromptLogic{}, func(name string, config map[string]string) interface{} {
		return prompt.NewBuildPromptLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&generate.ChatLogic{}, func(name string, config map[string]string) interface{} {
		return generate.NewChatLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&generate.StreamChatLogic{}, func(name string, config map[string]string) interface{} {
		return generate.NewStreamChatLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&response.BuildResponseLogic{}, func(name string, config map[string]string) interface{} {
		return response.NewBuildResponseLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&response.BuildRecallResponseLogic{}, func(name string, config map[string]string) interface{} {
		return response.NewBuildRecallResponseLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.RedLineLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewRedLineLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.FAQLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewFAQLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.KnowledgeEnhanceLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewKnowledgeEnhanceLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.SecurityReviewLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewSecurityReviewLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.SecurityReviewWordLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewSecurityReviewWordLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security.SecurityReviewRecallLogic{}, func(name string, config map[string]string) interface{} {
		return security.NewSecurityReviewRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&empty.EmptyLogic{}, func(name string, config map[string]string) interface{} {
		return empty.NewEmptyLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security_post.QuerySecurityJudgeLogic{}, func(name string, config map[string]string) interface{} {
		return security_post.NewQuerySecurityJudgeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security_post.RecallAndSafetyJudgeChoose{}, func(name string, config map[string]string) interface{} {
		return security_post.NewRecallAndSafetyJudgeChoose(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security_post.StaticQAJudgeLogic{}, func(name string, config map[string]string) interface{} {
		return security_post.NewStaticQAJudgeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&security_post.QueryAndQueryMergeSafetyJudge{}, func(name string, config map[string]string) interface{} {
		return security_post.NewQueryAndQueryMergeSafetyJudge(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&consumer.SaveDialogRecordLogic{}, func(name string, config map[string]string) interface{} {
		return consumer.NewSaveDialogRecordLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.TagMemberLogic{}, func(name string, config map[string]string) interface{} {
		return root.NewTagMemberLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root.MemberTagCoreV2Logic{}, func(name string, config map[string]string) interface{} {
		return root.NewMemberTagCoreV2Logic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordExistPostLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordExistPostLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordSearchRecallLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordSearchRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordSimilarRecallLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordSimilarRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordMergeAndFilterLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordMergeAndFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordGuideRecallLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordGuideRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordGenerateIdLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordGenerateIdLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordRandomGuideRecallLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordRandomGuideRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordChooseLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordChooseLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordGuideRecallV2Logic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordGuideRecallV2Logic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordParagraphRecallLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordParagraphRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&word.WordSpecifiedDocRecallOrGenLogic{}, func(name string, config map[string]string) interface{} {
		return word.NewWordSpecifiedDocRecallOrGenLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&router.AgentRouterLogic{}, func(name string, config map[string]string) interface{} {
		return router.NewAgentRouterLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&response.DefItemRespLogic{}, func(name string, config map[string]string) interface{} {
		return response.NewDefItemRespLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ContentRegulateLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewContentRegulateLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ImageTagCoreMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewImageTagCoreMetaFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.OutSiteLevelMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewOutSiteLevelMetaFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.AuthorInfoFetchLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewAuthorInfoFetchLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ChunkRecallAndRerankFetchLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewChunkRecallAndRerankFetchLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.AuthorTagCoreMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewAuthorTagCoreMetaFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ContentStatsFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewContentStatsFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.DocSummaryFetchLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewDocSummaryFetchLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ChildContentCoreMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewChildContentCoreMetaFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.KnowledgeBaseVisibilityMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewKnowledgeBaseVisibilityMetaFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&frameworkFilter.InitFilterLogic[entities.RequestContext, entities.User, entities.Item]{}, func(name string, config map[string]string) interface{} {
		return frameworkFilter.NewInitFilterReasonLogic[entities.RequestContext, entities.User, entities.Item](name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&frameworkFilter.FilterPostLogic[entities.RequestContext, entities.User, entities.Item]{}, func(name string, config map[string]string) interface{} {
		return frameworkFilter.NewFilterPostLogic[entities.RequestContext, entities.User, entities.Item](name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.ContentRegulateFilterLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewContentRegulateFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.EmptyMetaFilterLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewEmptyMetaFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.KbRecallSecurityFilterLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewKbRecallSecurityFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.KbRecallSiteLevelFilterLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewKbRecallSiteLevelFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.KbRecallBlackListFilterLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewKbRecallBlackListFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&mapping.ChatAnswer2SentenceLogic{}, func(name string, config map[string]string) interface{} {
		return mapping.NewChatAnswer2SentenceLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&response.UploadRespChanLogic{}, func(name string, config map[string]string) interface{} {
		return response.NewUploadRespChanLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&mapping.OverwriteConfigLogic{}, func(name string, config map[string]string) interface{} {
		return mapping.NewOverwriteConfigLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&mapping.Question2AnswerLogic{}, func(name string, config map[string]string) interface{} {
		return mapping.NewQuestion2AnswerLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&mapping.Doc2ChunkLogic{}, func(name string, config map[string]string) interface{} {
		return mapping.NewDoc2ChunkLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&mapping.StageConfigLogic{}, func(name string, config map[string]string) interface{} {
		return mapping.NewStageConfigLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.TruncateLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewTruncateLogic(name, config)
	})
	// Summary Recall 相关
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.KbZhihuRecallLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewKbZhihuRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.ZplusRecallLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewZplusRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.KbOutSiteRecallLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewKbOutSiteRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.KbReplenishArxivRecallLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewKbReplenishArxivRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&merge.KbRecallMergeAndLimitLogic{}, func(name string, config map[string]string) interface{} {
		return merge.NewKbRecallMergeAndLimitLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.KbRecallRebootRespLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewKbRecallRebootRespLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.KbRecallIoFilterLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewKbRecallIoFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.KbRecallIoFilterV2Logic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewKbRecallIoFilterV2Logic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&rerank.KbRecallChunkAndReRankLogic{}, func(name string, config map[string]string) interface{} {
		return rerank.NewKbRecallChunkAndReRankLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&rerank.KbRecallChunkAndScoreLogic{}, func(name string, config map[string]string) interface{} {
		return rerank.NewKbRecallChunkAndScoreLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&rerank.KbRecallChunkAndReRankV2BeforeLogic{}, func(name string, config map[string]string) interface{} {
		return rerank.NewKbRecallChunkAndReRankV2BeforeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&rerank.KbRecallChunkAndReRankV2AfterLogic{}, func(name string, config map[string]string) interface{} {
		return rerank.NewKbRecallChunkAndReRankV2AfterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&rerank.KbRecallChunkCiteBeforeLogic{}, func(name string, config map[string]string) interface{} {
		return rerank.NewKbRecallChunkCiteBeforeLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.KbEnhanceRecallLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewKbEnhanceRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&chat_cache.ChatCacheChooseLogic{}, func(name string, config map[string]string) interface{} {
		return chat_cache.NewChatCacheChooseLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&choose.ExpLogic{}, func(name string, config map[string]string) interface{} {
		return choose.NewExpLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&choose.RequestLegalityVerifyLogic{}, func(name string, config map[string]string) interface{} {
		return choose.NewRequestLegalityVerifyLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.RuceneLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewRuceneLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.RumRecallLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewRumRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.KbSameQuestionAnswerAppendLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewKbSameQuestionAnswerAppendLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recall.ForwardIndexRecallLogic{}, func(name string, config map[string]string) interface{} {
		return recall.NewForwardIndexRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&logic.SubGraphRecallLogic{}, func(name string, config map[string]string) interface{} {
		return logic.NewSubGraphRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&sub_logic.DeepSearchRecallLogic{}, func(name string, config map[string]string) interface{} {
		return sub_logic.NewDeepSearchRecallLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&root_logic.DeepSearchLogic{}, func(name string, config map[string]string) interface{} {
		return root_logic.NewDeepSearchLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.DocumentFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewDocumentFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&condition.SwitchConditionLogic{}, func(name string, config map[string]string) interface{} {
		return condition.NewSwitchConditionLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&merge.KbRecallSourceMergeLogic{}, func(name string, config map[string]string) interface{} {
		return merge.NewKbRecallSourceMergeLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&merge.KbRecallSourceSimilarLogic{}, func(name string, config map[string]string) interface{} {
		return merge.NewKbRecallSourceSimilarLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.TagCoreMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewTagCoreMetaFetcherLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.KbRecallTagFilterLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewKbRecallTagFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.KbRecallVisibilityFilterLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewKbRecallVisibilityFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&recallFilter.KbRecallSimHashFilterLogic{}, func(name string, config map[string]string) interface{} {
		return recallFilter.NewKbRecallSimHashFilterLogic(name, config)
	})
	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&meta_fetcher.ReadMetaFetcherLogic{}, func(name string, config map[string]string) interface{} {
		return meta_fetcher.NewReadMetaFetcherLogic(name, config)
	})

	logic_store.PutLogic[entities.RequestContext, entities.User, entities.Item](&empty.EmptyRootLogic{}, func(name string, config map[string]string) interface{} {
		return empty.NewEmptyRootLogic(name, config)
	})

	log.Infof(context.Background(), "PutLogic end")
	log.Infof(context.Background(), "InitZagDriver start")
	log.Infof(context.Background(), "InitZagDriver end")

	return nil
})

func Init(scene string) interface{} {
	sceneName = scene
	log.Infof(context.Background(), "initOnce: %s", sceneName)
	initOnce()
	if sceneName != graph_constant.ApiRecall {
		graph.InitZagDriver(sceneName)
	}
	return nil
}
