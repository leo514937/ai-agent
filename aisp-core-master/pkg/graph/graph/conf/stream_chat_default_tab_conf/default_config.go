package stream_chat_default_tab_conf

import (
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"github.com/spf13/cast"
)

// 默认常量
const (
	ChatHistoryLimit    = 3
	ChatHistoryNewLimit = 5
	ChatHistoryLimit10  = 10
	ChatHistoryLimit15  = 15
)

const (
	InitConfigStage      = "InitConfigStage"
	InitBeginConfigLogic = "initBeginConfig"
	InitConfigLogic      = "initConfig"
	RecallConfigStage    = "RecallConfigStage"
	RecallConfigLogic    = "recallConfig"
	RerankConfigStage    = "RerankConfigStage"
	RerankConfigLogic    = "rerankConfig"
	GenerateConfigStage  = "GenerateConfigStage"
	GenerateConfigLogic  = "generateConfig"
	AllConfigStagge      = "ConfigStage"

	// root
	RootStage         = "root"
	RootLogic         = "rootNode"
	UserInputStage    = "userInput"
	CopyUserMetaLogic = "copyUserMeta"
	UserMessageLogic  = "userMessage"

	// prepare
	PrepareStage                    = "Prepare"
	PrepareInitStage                = "PrepareInitStage"
	PrepareOtherStage               = "PrepareOtherStage"
	PrepareInitEmptyLogic           = "prepareInitEmpty"
	RequestConfigLogic              = "requestConfig"
	ChatHistoryLogic                = "chatHistory"
	SessionInfoLogic                = "SessionInfo"
	MemberTagCoreLogic              = "memberTagCore"
	QueryDefinitionLogic            = "queryDefinition"
	LoadApolloConfig                = "loadApolloConfig"
	QueryEmbeddingLogic             = "queryEmbeddingLogic"
	KnowledgeBaseInfoLogic          = "knowledgeBaseInfo"
	UniversalKnowledgeBaseInfoLogic = "universalKnowledgeBaseInfo"
	PreparerDataTidyLogic           = "dataTidyLogic"
	AuthorMetaInfoLogic             = "authorMetaInfo"

	PrepareMetaStage = "prepareMetaStage"
	MembersInfoLogic = "membersInfo"
	DocsInfoLogic    = "docsInfo"
	RefTextInfoLogic = "refTextInfo"

	// prepare 中的空算子
	EmptyPrepareStageLogic = "EmptyPrepareStage"
	EmptyPrepareLogic      = "emptyPrepare"

	EmptyPrepareEndStage = "EmptyPrepareEndStage"
	EmptyPrepareEndLogic = "emptyPrepareEnd"

	// 缓存读取
	CacheStage           = "CacheStage"
	ChatCacheChooseLogic = "chatCacheChoose"

	// 缓存未命中
	MissCacheStage = "MissCacheStage"
	MissCacheLogic = "missCache"

	// 处理空算子
	EmptyStage                    = "EmptyStage"
	HitCacheOrIllegalRequestStage = "hitCacheOrIllegalRequestStage"
	HitCacheLogic                 = "hitCache"
	IllegalRequestLogic           = "illegalRequest"

	// Research
	ResearchStage             = "ResearchStage"
	ResearchLogic             = "research"
	ResearchAfterHandlerLogic = "research_after_handler"

	// 非法请求
	RequestLegalityStage    = "RequestLegalityStage"
	RequestLegalityLogic    = "requestLegality"
	RequestKeyLegalityLogic = "requestKeyLegality"

	// agnent judge
	AgentJudgeStage                    = "AgentJudgeStage"
	AgentOverwriteConfigLogic          = "agentOverwriteConfig"
	SpecificRecallOverwriteConfigLogic = "specificRecallOverwriteConfig"

	// agnent judge
	AgentJudgeStage2           = "AgentJudgeStage2"
	AgentOverwriteConfigLogic2 = "agentOverwriteConfig2"

	// query 安全模块
	QuerySecurityStage         = "QuerySecurityStage"
	QuerySecurityLogic         = "querySecurity"
	QueryMergeSecurityLogic    = "queryMergeSecurity"
	QuerySecurityUnPassedStage = "QuerySecurityUnPassedStage"
	QuerySecurityUnPassedLogic = "querySecurityUnPassed"
	SecurityStage              = "Security"
	SecurityJudgeStage         = "SecurityJudgeStage"
	RedLineLogic               = "redLine"
	SecurityReviewLogic        = "securityReview"
	FaqLogic                   = "faq"
	SecurityPostLogic          = "securityPost"

	SecurityMStage       = "SecurityM"
	RedLineMLogic        = "redLineM"
	SecurityReviewMLogic = "securityReviewM"
	FaqMLogic            = "faqM"
	SecurityPostMLogic   = "securityPostM"

	// 相关追问跳转导流
	ExtraAnswerDisassemblyInfoStage = "ExtraAnswerDisassemblyInfoStage"
	ExtraAnswerCovertLogic          = "extraAnswerCovertLogic"

	// query merge
	QueryMergeStage      = "QueryMergeStage"
	QueryMergeLogic      = "queryMerge"
	EmptyQueryMergeLogic = "emptyQueryMerge"
	QueryRouterLogic     = "queryRouter"
	AgentRouterLogic     = "agentRouter"

	// DocRouter Judge
	DocRouterJudgeStage = "DocRouterJudgeStage"
	DocRouterJudge      = "docRouterJudge"
	IntentionCondition  = "intentionCondition"

	// recall
	KbRecallStage                            = "KbRecall"
	KbZhihuRecallLogic                       = "KbZhihuRecall"
	KbZhihuA4RecallLogic                     = "KbZhihuA4Recall"
	KbZhihuAuthorDocRecallLogic              = "KbZhihuAuthorDocRecall"
	KbArxivRecallLogic                       = "kbArxivRecall"
	KbPaperRecallLogic                       = "kbPaperRecall"
	KbReplenishArxivRecallLogic              = "kbReplenishArxivRecall"
	KbZhWikiRumRecallLogic                   = "kbZhWikiRumRecall"
	KbEnWikiRumRecallLogic                   = "kbEnWikiRumRecall"
	KbZhWikiRuceneRecallLogic                = "kbZhWikiRuceneRecall"
	KbEnWikiRuceneRecallLogic                = "kbEnWikiRuceneRecall"
	PersonalKnowledgeBaseRumRecallLogic      = "personalKnowledgeBaseRumRecall"
	PersonalKnowledgeBaseRuceneRecallLogic   = "personalKnowledgeBaseRuceneRecall"
	InternalKnowledgeBaseRumRecallLogic      = "internalKnowledgeBaseRumRecall"
	InternalKnowledgeBaseRuceneRecallLogic   = "internalKnowledgeBaseRuceneRecall"
	InternalKnowledgeBaseRecallSimMergeLogic = "internalKnowledgeBaseSimMerge"
	MountDoc2SpecifiedDocRecallLogic         = "mountDoc2SpecifiedDocRecall"
	SpecifiedDocRecallLogic                  = "specifiedDocRecall"
	KbSameQuestionAnswerAppendLogic          = "kbSameQuestionAnswerAppend"
	KbBingRecallLogic                        = "kbBingRecall"
	KbSougouRecallLogic                      = "kbSougouRecall"
	KbQuarkRecallLogic                       = "kbQuarkRecall"
	KbSerperRecallLogic                      = "kbSerperRecall"
	KbKexinRecallLogic                       = "kbKexinRecall"
	KbRecallSourceMergeLogic                 = "kbRecallSourceMerge"
	KbRecallOutSiteSourceMergeLogic          = "kbRecallOutSiteSourceMerge"
	KbRecallZhihuSourceMergeLogic            = "kbRecallZhihuSourceMerge"
	KbRecallPaperSourceMergeLogic            = "kbRecallPaperSourceMerge"
	KbZhihuAuthorDocSourceMergeLogic         = "kbZhihuAuthorDocSourceMerge"
	PersonalKnowledgeBaseRecallMergeLogic    = "personalKnowledgeBaseRecallMerge"
	PersonalKnowledgeBaseMergeLogic          = "personalKnowledgeBaseMerge"
	KbRecallFinalSourceMergeLogic            = "kbRecallFinalSourceMerge"
	QuKeywordFetcherLogic                    = "quKeywordFetcher"
	BgeEmbeddingFetcherLogic                 = "bgeEmbeddingFetcher"
	BgeM3EmbeddingFetcherLogic               = "bgeM3EmbeddingFetcher"
	QueryMergeFetcherEmptyLogic              = "queryMergeFetcherEmptyLogic"
	KbOutSiteRuceneRecallLogic               = "kbOutSiteRuceneRecall"
	KbOutSiteRumRecallLogic                  = "kbOutSiteRumRecall"
	KbZPlusAutomotiveRecallLogic             = "kbZPlusAutomotiveRecallLogic" // 知+ 汽车行业自建召回
	DeepSearchRecallLogic                    = "deepSearchRecallLogic"
	DeepSearchLogic                          = "deepSearchLogic"

	// 召回
	SubGraphRecallStage      = "SubGraphRecallStage"
	SubGraphRecallBeginLogic = "recallBeginLogic"
	SubGraphRecallLogic      = "subGraphRecallLogic"

	// meta fetcher
	RecallMergeStage = "RecallMergeStage"
	RecallMergeLogic = "recallMergeLogic"

	// meta fetcher
	QueryMergeMetaFetcherStage = "QueryMergeMetaFetcherStage"

	// meta fetcher
	RecallMetaFetcherStage                           = "RecallMetaFetcherStage"
	KbRecallMetaFetcherMergeLogic                    = "kbRecallMetaFetcherMerge"
	KbRecallMetaFetcherLogic                         = "kbRecallMetaFetcher"
	AuthorTagFetcherLogic                            = "authorTagFetcher"
	PaperMetaFetcherMergeLogic                       = "paperMetaFetcherMerge"
	PaperMetaFetcherLogic                            = "paperMetaFetcher"
	ContentStatsFetcherLogic                         = "contentStatsFetcher"
	ReadFetcherLogic                                 = "readFetcherLogic"
	DocumentFetcherLogic                             = "documentFetcherLogic"
	KbZhihuRecallMetaFetcherMergeLogic               = "kbZhihuRecallMetaFetcherMerge"
	OutSiteRecallMetaFetcherMerge                    = "outSiteRecallMetaFetcherMerge"
	OutSiteRecallLevelMetaFetcher                    = "outSiteRecallLevelMetaFetcher"
	KbZhihuRecallMetaFetcherLogic                    = "kbZhihuRecallMetaFetcher"
	KbZhihuRecallTagFetcherLogic                     = "kbZhihuRecallTagFetcher"
	MountDoc2SpecifiedDocMetaFetcherLogic            = "mountDoc2SpecifiedDocMetaFetcher"
	MountDoc2SpecifiedDocInternalMetaFetcherLogic    = "mountDoc2SpecifiedDocInternalMetaFetcher"
	KbRecallParentMetaFetcherLogic                   = "kbRecallParentMetaFetcher"
	KbRecallChildMetaFetcherLogic                    = "kbRecallChildMetaFetcher"
	KbRecallAuthorMetaFetcherLogic                   = "kbRecallAuthorMetaFetcher"
	KbRecallQuestion2AnswerLogic                     = "kbRecallQuestion2AnswerLogic"
	PersonalKnowledgeBaseRecallMetaFetcherMergeLogic = "personalKnowledgeBaseRecallMetaFetcherMerge"
	PersonalKnowledgeBaseRecallMetaFetcherLogic      = "personalKnowledgeBaseRecallMetaFetcher"
	PersonalKnowledgeBaseVisibilityMetaFetcherLogic  = "personalKnowledgeBaseVisibilityMetaFetcher"
	InternalKnowledgeBaseRecallMetaFetcherMergeLogic = "internalKnowledgeBaseEmptyMerge"
	InternalKnowledgeBaseRecallMetaFetcherLogic      = "internalKnowledgeBaseMetaFetcher"

	ContentCoreMetaFetcherLogic = "ContentCoreMetaFetcher"

	// 站内站外拆分
	RecallIoFilterStage      = "RecallIoFilterStage"
	RecallInsideFilterLogic  = "RecallInsideFilter"
	RecallOutsideFilterLogic = "RecallOutsideFilter"

	// 召回过滤
	RecallFilterStage     = "RecallFilterStage"
	RecallInitMergeLogic  = "RecallInitMerge"
	RecallInitFilterLogic = "RecallInitFilter"
	RecallPostFilterLogic = "RecallPostFilter"

	// 站内过滤
	OnSiteStageFilterStage           = "OnSiteFilterStage"
	OnSiteInitFilterLogic            = "onSiteInitFilter"
	ValidContentRegulateFetcherLogic = "validContentRegulateFetcher"
	ContentRegulateFilterLogic       = "contentRegulateFilter"
	EmptyMetaFilterLogic             = "emptyMetaFilter"
	EmptyContentFilterLogic          = "emptyContentFilter"
	KbVisibilityFilterLogic          = "kbVisibilityFilter"
	SiteLevelFilterLogic             = "siteLevelFilter"
	RecallBlackListFilterLogic       = "recallBlackListFilter"
	OnSitePostFilterLogic            = "onSitePostFilter"
	TagCoreMetaFetcherLogic          = "tagCoreMetaFetcherLogic"
	KbRecallTagFilterLogic           = "kbRecallTagFilterLogic"

	// 站外过滤
	OutSiteStageFilterStage          = "OutSiteStageFilter"
	OutSiteInitFilterLogic           = "outSiteInitFilter"
	FinalStageFilterStage            = "finalStageFilter"
	FinalInitMergeFilterLogic        = "finalInitMergeFilter"
	FinalInitFilterLogic             = "finalInitFilter"
	FinalPostFilterLogic             = "finalPostFilter"
	ValidContentSecurityFetcherLogic = "validContentSecurityFetcher"
	ContentSecurityFilterLogic       = "contentSecurityFilter"
	OutSitePostFilterLogic           = "outSitePostFilter"

	// 召回安全过滤
	RecallSecurityFilterStage              = "RecallSecurityFilterStage"
	RecallSecurityInitFilterLogic          = "recallSecurityInitFilterLogic"
	RecallSecurityValidContentFetcherLogic = "recallSecurityValidContentFetcher"
	RecallSecurityContentFilterLogic       = "recallSecurityContentFilter"
	RecallSecurityPostFilterLogic          = "recallSecurityPostFilterLogic"

	// 合并重排
	KbRecallHandleStage                 = "KbRecallHandleStage"
	KbRecallChunkAndReRankV2BeforeLogic = "kbRecallChunkAndReRankV2Before"

	// 合并后基于内容的 simhash 去重
	KbRecallSimhashFilterLogic = "KbRecallSimhashFilterLogic"

	// 召回数量/token数限制
	RecallLimitLogic = "recallLimit"

	// 安全判断
	RecallAndSafetyJudgeChooseStage = "recallAndSafetyJudgeChooseStage"
	RecallAndSafetyJudgeChooseLogic = "recallAndSafetyJudgeChoose"

	// QueryAndQueryMerge 安全判断
	QueryAndQueryMergeSafetyJudgeStage = "QueryAndQueryMergeSafetyJudgeStage"
	QueryAndQueryMergeSafetyJudge      = "QueryAndQueryMergeSafetyJudge"
	// QueryAndQueryMerge 安全判断(未通过)
	QueryAndQueryMergeSafetyUnPassedStage = "QueryAndQueryMergeSafetyUnPassedStage"
	QueryAndQueryMergeSafetyUnPassedLogic = "QueryAndQueryMergeSafetyUnPassed"

	// 安全不通过
	RecallAndSafetyUnPassedStage = "recallAndSafetyUnPassedStage"
	RecallAndSafetyUnPassedLogic = "recallAndSafetyUnPassedLogic"

	// author search agent
	AuthorSearchRecallLogic     = "AuthorSearchRecallLogic"
	AuthorSearchSelfRecallLogic = "AuthorSearchSelfRecallLogic"
	AuthorSearchMergeLogic      = "AuthorSearchMerge"

	// 发送Recall 结果到 chan
	UploadRecallChanStage = "uploadRecallChanStage"
	UploadRecallChanLogic = "UploadRecallChan"

	UploadRecallChanThenBreakStage = "UploadRecallChanThenBreakStage"
	UploadRecallChanThenBreakLogic = "UploadRecallChanThenBreakLogic"

	// 召回到模型的重排序（V2 Rank 生效）
	Recall2ModelReRankStage        = "Recall2ModelReRankStage"
	Recall2ModelChunkAndScoreLogic = "recall2ModelChunkAndScoreLogic"
	Recall2ModelReRankLogic        = "recall2ModelReRankLogic"

	// RerankStage
	RerankStage              = "RerankStage"
	KbRecallChunkCiteLogic   = "KbRecallChunkCite"
	RerankBeforeLogic        = "RerankBefore"
	RecallChunkAndScoreLogic = "RecallChunkAndScore"
	RerankAfterLogic         = "RerankAfter"

	// 大模型生成
	GenerateStage         = "generate"
	DirectChatLogic       = "directChat"
	WordGenerateStage     = "wordGenerate"
	StreamChatLogic       = "streamChat"
	ChatLogic             = "chat"
	Answer2SentenceLogic  = "answer2Sentence"
	RecallRebootRespLogic = "recallRebootResp"

	// Response 安全
	RespSecurityStage     = "RespSecurityStage"
	RespSecurityPostLogic = "respSecurityPost"

	// 回答安全
	AnswerSecurityStage             = "AnswerSecurityStage"
	AnswerSecurityUnPassStage       = "AnswerSecurityUnPassStage"
	AnswerSecurityResultStage       = "AnswerSecurityResultStage"
	AnswerSecurityBeforeUnPassLogic = "answerSecurityBeforeUnPass"
	AnswerSecurityPassedLogic       = "answerSecurityPassed"
	AnswerSecurityUnPassLogic       = "answerSecurityUnPass"
	AnswerSecurityMergeLogic        = "answerSecurityMerge"
	SecurityReviewOutLogic          = "securityReviewOut"
	AnswerSecurityBeforePostLogic   = "answerSecurityBeforePost"
	AnswerSecurityPostLogic         = "answerSecurityPost"
	// 词安全
	WordSecurityStage                = "WordSecurityStage"
	RelevantQuerySecurityReviewLogic = "relevantQuerySecurityReview"
	RelevantQuerySecurityPostLogic   = "relevantQuerySecurityPost"
	UploadQueryChanLogic             = "uploadQueryChan"

	// 返回
	ResponseStage            = "response"
	SaveDialogLogic          = "saveDialog"
	TracingRecordLogic       = "tracingRecord"
	RecallTracingRecordLogic = "recallTracingRecord"
	SaveQueryResultLogic     = "saveQueryResult"
	LastNRecordLogic         = "lastNRecord"
	ResponseLogic            = macro.ResponseNode
	RecallResponseLogic      = macro.ResponseNode
)

// StaticConfigMap 静态配置
var StaticConfigMap = map[string]map[string]string{
	RecallTracingRecordLogic: {
		conf.SkipRuceneTracing.ToConvert(): "true",
		conf.TracingKafkaTopic.ToConvert(): string(macro.RecallTracing),
	},
	BgeEmbeddingFetcherLogic: {
		conf.EmbeddingModelName: "bge-embedding-ai-zhida-online",
		conf.ConfigOutputNames:  graph_macro.ZagKeyQueryMergeEmbedding,
	},
	BgeM3EmbeddingFetcherLogic: {
		conf.EmbeddingModelName: "bge-m3-common-for-zhida-online",
		conf.EmbeddingType:      conf.EmbeddingTypeByBgeM3,
	},
	CopyUserMetaLogic: {
		conf.ConfigOutputNames: util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyQueryText,
			graph_macro.ZagKeyMemberId, graph_macro.ZagKeyScene, graph_macro.ZagKeySessionId),
	},
	ChatHistoryLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyHistoryDialogue,
	},
	QueryRouterLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyIntention,
	},
	AuthorSearchRecallLogic: {
		conf.RumTableName:                    macro.ZhidaAuthorBgeRumTable,
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceAuthorBge.String(),
	},
	AuthorSearchSelfRecallLogic: {
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceAuthorBge.String(),
	},
	KbZhWikiRumRecallLogic: {
		conf.RumTableName:                    strings.Join([]string{macro.WikiZhTitleAndContentRumTable, macro.WikiZhTitleRumTable, macro.WikiZhContentRumTable}, ","),
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceZhWikiRum.String(),
	},
	KbEnWikiRumRecallLogic: {
		conf.RumTableName:                    strings.Join([]string{macro.WikiEnTitleAndContentRumTable, macro.WikiEnTitleRumTable, macro.WikiEnContentRumTable}, ","),
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceEnWikiRum.String(),
	},
	AuthorSearchMergeLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyAuthorItemsAfterMerge,
	},
	QueryEmbeddingLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyQueryEmbedding,
	},
	KbBingRecallLogic: {
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceBing.String(),
	},
	KbSougouRecallLogic: {
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceSougou.String(),
	},
	KbQuarkRecallLogic: {
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceQuark.String(),
	},
	KbSerperRecallLogic: {
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceSerper.String(),
	},
	KbKexinRecallLogic: {
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceKexin.String(),
	},
	KbOutSiteRuceneRecallLogic: {
		conf.RucenePath:                      model.ZhidaOutSitePath,
		conf.RuceneIndex:                     model.ZhidaOutSiteIndex,
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceOutSiteRucene.String(),
	},
	KbZhWikiRuceneRecallLogic: {
		conf.RucenePath:                      model.WikiZhPath,
		conf.RuceneIndex:                     model.WikiZhIndex,
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceZhWikiRucene.String(),
	},
	KbEnWikiRuceneRecallLogic: {
		conf.RucenePath:                      model.WikiEnPath,
		conf.RuceneIndex:                     model.WikiEnIndex,
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceEnWikiRucene.String(),
	},
	PersonalKnowledgeBaseRumRecallLogic: {
		conf.RumTableName:                    macro.PersonalKnowledgeBaseContentRumTable,
		conf.SummaryRecallSource.ToConvert(): conf.PersonalKnowledgeBaseRum.String(),
	},
	PersonalKnowledgeBaseRuceneRecallLogic: {
		conf.RucenePath:                      model.PersonalKnowledgeDocPath,
		conf.RuceneIndex:                     model.PersonalKnowledgeDocIndex,
		conf.SummaryRecallSource.ToConvert(): conf.PersonalKnowledgeBaseRucene.String(),
	},
	InternalKnowledgeBaseRumRecallLogic: {
		conf.RumTableName:                    strings.Join([]string{macro.InternalKnowledgeBaseTitleRumTable, macro.InternalKnowledgeBaseQuestionRumTable}, ","),
		conf.SummaryRecallSource.ToConvert(): conf.InternalKnowledgeBaseRum.String(),
	},
	InternalKnowledgeBaseRuceneRecallLogic: {
		conf.RucenePath:                      model.InternalKnowledgeDocPath,
		conf.RuceneIndex:                     model.InternalKnowledgeDocIndex,
		conf.SummaryRecallSource.ToConvert(): conf.InternalKnowledgeBaseRucene.String(),
	},
	KbOutSiteRumRecallLogic: {
		conf.RumTableName:                    macro.ZhidaOutSiteRumTable,
		conf.SummaryRecallSource.ToConvert(): conf.KbSourceOutSiteRum.String(),
	},
	ChatCacheChooseLogic: {
		conf.ConfigOutputNames: util2.JoinNamesToString(graph_macro.ZagKeyHitResponseCache),
	},
	DocRouterJudge: {
		conf.ConfigOutputNames: util2.JoinNamesToString(graph_macro.ZagKeyDocRoute),
	},
	RedLineLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyRedLineAnswer,
	},
	SecurityReviewLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyQuerySecurityReviewIsAvailable,
	},
	FaqLogic: {
		conf.ConfigOutputNames: util2.JoinNamesToString(graph_macro.ZagKeyFaqAnswer, graph_macro.ZagKeyShowRecallIfFaqAnswerPresent),
	},
	SecurityPostLogic: {
		conf.SecurityBusinessStage.ToConvert(): cast.ToString(int32(proto.BusinessStage_QUERY)),
		conf.ConfigOutputNames:                 util2.JoinNamesToString(graph_macro.ZagKeyQuerySecurityAllPass),
	},
	RedLineMLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyQueryMergeRedLineAnswer,
	},
	SecurityReviewMLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyQueryMergeSecurityReviewIsAvailable,
	},
	FaqMLogic: {
		conf.ConfigOutputNames: util2.JoinNamesToString(graph_macro.ZagKeyQueryMergeFaqAnswer, graph_macro.ZagKeyShowRecallIfQueryMergeFaqAnswerPresent),
	},
	SecurityPostMLogic: {
		conf.SecurityBusinessStage.ToConvert(): cast.ToString(int32(proto.BusinessStage_QUERY_MERGE)),
		conf.ConfigOutputNames:                 util2.JoinNamesToString(graph_macro.ZagKeyQueryMergeSecurityAllPass),
	},
	IntentionCondition: {
		conf.ConfigSwitchConditionSwitchBranchMap: util.GetJSONIgnoreError(map[string]string{"mock": "mock"}),
		conf.ConfigSwitchConditionDefaultBranch:   cast.ToString(entities.SpecifiedDocAny),
	},
	KbRecallSourceMergeLogic: {
		conf.ConfigOutputNames: graph_macro.ZagKeyRecallItemsAfterMerge,
	},
	UploadRecallChanLogic: {
		conf.ConfigChatMappingType: entities.ChatMappingTypeRecallChunk.ToConvertStr(),
		conf.ConfigOutputNames:     graph_macro.ZagKeyRecallItemsAfterMergeAndLimit,
	},
	UploadQueryChanLogic: {
		conf.ConfigChatMappingType: entities.ChatMappingTypeQuestion.ToConvertStr(),
		conf.ConfigOutputNames:     graph_macro.ZagKeyRelateQueries,
	},
	RecallAndSafetyJudgeChooseLogic: {
		conf.ConfigInputNames: util2.JoinNamesToString(graph_macro.ZagKeyQuerySecurityAllPass, graph_macro.ZagKeyQueryMergeSecurityAllPass,
			graph_macro.ZagKeyFaqAnswer, graph_macro.ZagKeyQueryMergeFaqAnswer,
			graph_macro.ZagKeyShowRecallIfFaqAnswerPresent, graph_macro.ZagKeyShowRecallIfQueryMergeFaqAnswerPresent),
	},
	QueryAndQueryMergeSafetyJudge: {
		conf.ConfigInputNames: util2.JoinNamesToString(graph_macro.ZagKeyQuerySecurityAllPass, graph_macro.ZagKeyQueryMergeSecurityAllPass),
	},
	StreamChatLogic: {
		conf.ConfigOutputNames: util2.JoinNamesToString(graph_macro.ZagKeyAnswerSecurityPass,
			graph_macro.ZagKeyStreamChatBeginMs, graph_macro.ZagKeyFirstTokenMs, graph_macro.ZagKeyStreamChatEndMs),
	},
	ResponseLogic: {
		conf.ConfigOutputNames: util2.JoinNamesToString(graph_macro.ZagKeyRelevantQueries, graph_macro.ZagKeyCurrentAnswer),
	},
	SaveDialogLogic: {
		conf.ConfigInputNames: util2.JoinNamesToString(graph_macro.ZagKeyCurrentQuery, graph_macro.ZagKeyCurrentAnswer,
			graph_macro.ZagKeyQueryMergeRedLineAnswer, graph_macro.ZagKeyQueryMergeRedLineAnswer,
			graph_macro.ZagKeyFaqAnswer, graph_macro.ZagKeyQueryMergeFaqAnswer,
			graph_macro.ZagKeyQuerySecurityReviewIsAvailable, graph_macro.ZagKeyQueryMergeSecurityReviewIsAvailable),
	},
	TracingRecordLogic: {
		conf.ConfigInputNames: util2.JoinNamesToString(graph_macro.ZagKeyStreamChatBeginMs, graph_macro.ZagKeyFirstTokenMs, graph_macro.ZagKeyStreamChatEndMs,
			graph_macro.ZagKeyRecallItemsAfterMergeAndLimit, graph_macro.ZagKeyRelevantQueries),
	},
	SaveQueryResultLogic: {
		conf.ConfigInputNames: util2.JoinNamesToString(graph_macro.ZagKeyQueryText, graph_macro.ZagKeyScene, graph_macro.ZagKeyHitResponseCache,
			graph_macro.ZagKeyQuerySecurityAllPass, graph_macro.ZagKeyQueryMergeSecurityAllPass, graph_macro.ZagKeyAnswerSecurityPass,
			graph_macro.ZagKeyRecallItemsAfterMergeAndLimit, graph_macro.ZagKeyRelevantQueries),
	},
	LastNRecordLogic: {
		conf.ConfigInputNames: util2.JoinNamesToString(graph_macro.ZagKeyQuerySecurityAllPass, graph_macro.ZagKeyQueryMergeSecurityAllPass,
			graph_macro.ZagKeyRecallItemsAfterMergeAndLimit),
	},
	FinalInitFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	FinalPostFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	OnSiteInitFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	OnSitePostFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	OutSiteInitFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	OutSitePostFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	RecallSecurityInitFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	RecallSecurityPostFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	RecallInitFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	RecallPostFilterLogic: {
		conf.ConfigRegulateFilter: conf.ConfigRegulateFilter,
	},
	AnswerSecurityPostLogic: {
		conf.SecurityBusinessStage.ToConvert(): cast.ToString(int32(proto.BusinessStage_GENERATION)),
	},
	RelevantQuerySecurityPostLogic: {conf.SecurityBusinessStage.ToConvert(): cast.ToString(int32(proto.BusinessStage_RELEVANT_QUERY))},
}
