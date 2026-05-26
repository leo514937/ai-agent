package suggest_query_conf

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"github.com/spf13/cast"
)

const (
	// stages
	RootStage   = "root"
	RecallStage = "recall"
	MergeStage  = "merge"

	// logics
	RootNodeLogic    = "RootNode"
	UserMessageLogic = "UserMessage"
	UserTagsLogic    = "UserTags"

	WordMergeAndFilterLogic = "WordMergeAndFilter"

	/// ============ 预制词 begin ============
	WordGuideV2RecallLogic = "WordGuideV2Recall"
	/// ============ 预制词 end ============

	/// ============ 相关追问 begin ============
	RelatedWordCacheStage     = "RelatedWordCacheStage"
	RelatedWordGetCacheLogic  = "RelatedWordGetCacheLogic"
	RelatedWordSaveCacheLogic = "RelatedWordSaveCacheLogic"

	// 追问相关词 拆解请求信息为知乎站内召回
	RelatedWordDisassemblyInfoStage      = "RelatedWordDisassemblyInfoStage"
	RelatedWordDisassemblyInfoStageLogic = "RelatedWordDisassemblyInfoStageLogic"

	// 追问相关词 获取Meta信息
	RelatedWordMetaFetcherStage       = "RelatedWordMetaFetcherStage"
	RelatedWordMetaFetcherLogic       = "RelatedWordMetaFetcher"
	RelatedWordParentMetaFetcherLogic = "RelatedWordParentMetaFetcher"
	RelatedWordChildMetaFetcherLogic  = "RelatedWordChildMetaFetcher"
	RelatedWordQuestion2AnswerLogic   = "RelatedWordQuestion2AnswerLogic"
	RelatedWordCovertLogic            = "RelatedWordCovertLogic"

	RelatedWordChatGenerateStage = "RelatedWordChatGenerateStage"
	RelatedWordChatGenerateLogic = "RelatedWordChatGenerateLogic"
	Answer2SentenceLogic         = "Answer2Sentence"

	RelatedWordAnswerSecurityStage = "RelatedWordAnswerSecurityStage"
	RelatedWordSecurityReviewLogic = "RelatedWordSecurityReviewLogic"
	RelatedWordSecurityPostLogic   = "RelatedWordSecurityPostLogic"
	RelatedWordSecurityFinalLogic  = "RelatedWordSecurityFinalLogic"

	RelatedWordCacheJudgeStage = "RelatedWordCacheJudgeStage"
	RelatedWordNormalLogic     = "RelatedWordNormalLogic"
	RelatedWordBreakLogic      = "RelatedWordBreakLogic"
	/// ============ 相关追问 end ============

	/// ============ 指定文档相关追问词 begin ============
	SpecifiedDocRelatedWordRecallStage = "SpecifiedDocRelatedWordRecallStage"
	SpecifiedDocRelatedWordRecallLogic = "SpecifiedDocRelatedWordRecall"

	SpecifiedDocRelatedWordGenStage = "SpecifiedDocRelatedWordGenStage"
	SpecifiedDocRelatedWordGenLogic = "SpecifiedDocRelatedWordGen"

	SpecifiedDocRelatedWordRecallMergeStage = "SpecifiedDocRelatedWordRecallMergeStage"
	SpecifiedDocRelatedWordRecallMergeLogic = "SpecifiedDocRelatedWordRecallMerge"
	/// ============ 指定文档相关追问词 end ============

	// recall
	KbRecallStage       = "kbRecall"
	KbRecallCacheLogic  = "KbRecallCacheLogic"
	KbRecallFilterLogic = "KbRecallFilterLogic"
	KbZhihuRecallLogic  = "KbZhihuRecall"

	// 站内类型过滤
	RecallIoFilterStage     = "RecallIoFilterStage"
	RecallInsideFilterLogic = "RecallInsideFilter"

	// 召回到模型的重排序（V2 Rank 生效）
	Recall2ModelReRankStage        = "Recall2ModelReRankStage"
	Recall2ModelChunkAndScoreLogic = "Recall2ModelChunkAndScoreLogic"
	Recall2ModelReRankLogic        = "Recall2ModelReRankLogic"

	// meta fetcher
	RecallMetaFetcherStage         = "RecallMetaFetcherStage"
	ContentCoreMetaFetcherLogic    = "ContentCoreMetaFetcher"
	KbRecallMetaFetcherLogic       = "kbRecallMetaFetcher"
	KbRecallParentMetaFetcherLogic = "kbRecallParentMetaFetcher"
	KbRecallChildMetaFetcherLogic  = "kbRecallChildMetaFetcher"

	/// ============ 相关追问是否存在 ============
	RelatedWordIsExistStage      = "RelatedWordIsExistStage"
	RelatedWordIsExistLogic      = "RelatedWordIsExist"
	RelatedWordExistDefaultLogic = "RelatedWordExistDefault"
)

// GetStaticConfigMap 获取静态配置
var StaticConfigMap = map[string]map[string]string{
	// 相关词
	KbRecallCacheLogic: {
		conf.ConfigOutputNames: util2.JoinNamesToString(graph_macro.ZagKeyRelatedWordIsHitCache),
	},
	RelatedWordGetCacheLogic: {
		conf.ConfigOutputNames: util2.JoinNamesToString(graph_macro.ZagKeyRelatedWordIsHitCache),
	},
	RelatedWordSecurityPostLogic:       {conf.SecurityBusinessStage.ToConvert(): cast.ToString(int32(proto.BusinessStage_RELEVANT_QUERY))},
	SpecifiedDocRelatedWordRecallLogic: {conf.ConfigRecallOrGen: conf.ConfigRecallOrGenByRecall},
	SpecifiedDocRelatedWordGenLogic:    {conf.ConfigRecallOrGen: conf.ConfigRecallOrGenByGen},
}
