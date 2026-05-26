package stream_chat_default_tab_conf

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	searchThrift "git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// NotAllowRetryAnswerTrafficSource 不允许重答的流量来源
// 基本上在开发新的引流源时就确定了业务形态，所以这里没有太大必要放在apollo中
var NotAllowRetryAnswerTrafficSource = []proto.TrafficSource{
	proto.TrafficSource_ai_search_card_preview,
	proto.TrafficSource_entity_preview,
	proto.TrafficSource_search_tab_preview,
	proto.TrafficSource_ai_search_card_full_search_preview,
	proto.TrafficSource_search_entity_preview,
	proto.TrafficSource_ai_search_general,
}

var TrafficSourceOverwriteLogicConfigMap = map[proto.TrafficSource]map[proto.ClientSource]map[string]map[string]string{
	proto.TrafficSource_ai_search_card_preview: {
		proto.ClientSource_PC_WEB:     trafficSourceByAiSearchCardPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByAiSearchCardPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByAiSearchCardPreview,
	},
	proto.TrafficSource_ai_search_card: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreviewAndUnrestrictedModel,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreviewAndUnrestrictedModel,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreviewAndUnrestrictedModel,
	},
	// TODO 目前 full_search 与 普通版 策略一直，原因为前后端老师上错业务逻辑
	// TODO 如果后期 再次启动实验 记得要改这里
	proto.TrafficSource_ai_search_card_full_search_preview: {
		proto.ClientSource_PC_WEB:     trafficSourceByAiSearchCardPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByAiSearchCardPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByAiSearchCardPreview,
	},
	proto.TrafficSource_ai_search_card_full_search: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreviewAndUnrestrictedModel,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreviewAndUnrestrictedModel,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreviewAndUnrestrictedModel,
	},
	proto.TrafficSource_entity: {
		proto.ClientSource_PC_WEB:     trafficSourceByEntity,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByEntity,
		proto.ClientSource_MOBILE_WEB: trafficSourceByEntity,
	},
	proto.TrafficSource_entity_preview: {
		proto.ClientSource_PC_WEB:     trafficSourceByEntityPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByEntityPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByEntityPreview,
	},
	proto.TrafficSource_comment_entity: {
		proto.ClientSource_PC_WEB:     trafficSourceByEntity,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByEntity,
		proto.ClientSource_MOBILE_WEB: trafficSourceByEntity,
	},
	proto.TrafficSource_underlined_word: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreview,
	},
	// TODO
	proto.TrafficSource_noanswer_search: {
		proto.ClientSource_PC_WEB:     trafficSourceNoBingNoReferencesFlag,
		proto.ClientSource_ZHIHU_APP:  trafficSourceNoBingNoReferencesFlag,
		proto.ClientSource_MOBILE_WEB: trafficSourceNoBingNoReferencesFlag,
	},
	proto.TrafficSource_ai_search_query: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreview,
	},
	// TODO
	proto.TrafficSource_suggestion: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreview,
	},
	proto.TrafficSource_below_banner_question: {
		proto.ClientSource_PC_WEB:     trafficSourceByBelowBannerQuestion,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByBelowBannerQuestion,
		proto.ClientSource_MOBILE_WEB: trafficSourceByBelowBannerQuestion,
	},
	proto.TrafficSource_right_banner_question: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreview,
	},
	proto.TrafficSource_ai_summary_under_answer: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreview,
	},
	proto.TrafficSource_unsatisfied_search: {
		proto.ClientSource_PC_WEB:     trafficSourceByAllowBing,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByAllowBing,
		proto.ClientSource_MOBILE_WEB: trafficSourceByAllowBing,
	},
	proto.TrafficSource_search_tab: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreviewAndUnrestrictedModel,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreviewAndUnrestrictedModel,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreviewAndUnrestrictedModel,
	},
	proto.TrafficSource_search_tab_preview: {
		proto.ClientSource_PC_WEB:     trafficSourceNoBingNoReferencesFlag,
		proto.ClientSource_ZHIHU_APP:  trafficSourceNoBingNoReferencesFlag,
		proto.ClientSource_MOBILE_WEB: trafficSourceNoBingNoReferencesFlag,
	},
	proto.TrafficSource_follow_query: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreview,
	},
	proto.TrafficSource_viewpoint_page: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreview,
	},
	proto.TrafficSource_question_edit_page: {
		proto.ClientSource_PC_WEB:     trafficSourceByNotPreview,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByNotPreview,
		proto.ClientSource_MOBILE_WEB: trafficSourceByNotPreview,
	},
	proto.TrafficSource_zhida_gr_demo: {
		proto.ClientSource_PC_WEB:     trafficSourceByZhiDaGrDemo,
		proto.ClientSource_ZHIHU_APP:  trafficSourceByZhiDaGrDemo,
		proto.ClientSource_MOBILE_WEB: trafficSourceByZhiDaGrDemo,
	},
}

// =====================================================================================================================

var trafficSourceByZhiDaGrDemo = map[string]map[string]string{
	ChatLogic: {
		conf.ChatDisable: "true",
	},
	StreamChatLogic: {
		conf.StreamChatDisableReferences: "true",
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			IsCustom:                    true,
			SystemPromptId:              "zhida_summary_system_concise",
			SystemDefaultPromptTemplate: conf.PromptByQwenSystem,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v2", conf.PromptByQwenUser, ""),
				conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByQueryOrQueryDefinition("query_definition", conf.PromptByQueryDefinition, ""),
			},
		}.ToJsonString(),
	},
	KbOutSiteRumRecallLogic: {
		conf.ConfigRecallSize: "0",
	},
	KbOutSiteRuceneRecallLogic: {
		conf.ConfigRecallSize: "0",
	},
	FaqLogic: {
		conf.ConfigFaqKey: string(conf.ZhihaituFAQ),
	},
	FaqMLogic: {
		conf.ConfigFaqKey: string(conf.ZhihaituFAQ),
	},
	KbBingRecallLogic: {
		conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
			OrderGroup: 1,
			RecallSize: 8,
			Freshness:  "2010-01-01..2024-06-30"}),
	},
	KbZhihuRecallLogic: {
		conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
			OrderGroup: 0,
			RecallSize: 16,
			Vertical:   []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
			TimeBefore: 1719763199, // 2024-06-30 23:59:59
		}),
	},
}

var trafficSourceByAllowBing = map[string]map[string]string{
	ChatHistoryLogic: {
		conf.ChatHistorySkip.ToConvert(): "true",
	},
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	SaveQueryResultLogic: {
		// 不开启预制词缓存，走全量缓存
		conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
	},
}

var trafficSourceNoBingNoReferencesFlag = map[string]map[string]string{
	ChatHistoryLogic: {
		conf.ChatHistorySkip.ToConvert(): "true",
	},
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbBingRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSougouRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbQuarkRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSerperRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	StreamChatLogic: {
		conf.StreamChatDisableReferences: "true",
	},
	SaveQueryResultLogic: {
		// 不开启预制词缓存，走全量缓存
		conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
	},
}

var trafficSourceByNotPreview = map[string]map[string]string{
	ChatHistoryLogic: {
		conf.ChatHistorySkip.ToConvert(): "true",
	},
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbBingRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSougouRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbQuarkRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSerperRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	SaveQueryResultLogic: {
		// 不开启预制词缓存，走全量缓存
		conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
	},
}

var trafficSourceByNotPreviewAndUnrestrictedModel = map[string]map[string]string{
	QueryRouterLogic: {
		conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
	},
	ChatHistoryLogic: {
		conf.ChatHistorySkip.ToConvert(): "true",
	},
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbBingRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSougouRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbQuarkRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSerperRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	SaveQueryResultLogic: {
		// 不开启预制词缓存，走全量缓存
		conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
	},
	StreamChatLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
			ModelName: "virtual-llm-searchcard-online",
			MaxTokens: lo.ToPtr[int32](2048),
			Stop: []string{
				"<|im_end|>",
			},
			Temperature:       lo.ToPtr[float32](0.8),
			TopP:              lo.ToPtr[float32](0.9),
			TopK:              lo.ToPtr[int32](50),
			RepetitionPenalty: lo.ToPtr[float32](1.1),
			PresencePenalty:   nil,
			FrequencyPenalty:  nil,
			Stage:             proto.BusinessStage_GENERATION,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_TAB.String(),
			},
		}.ToJsonString(),
	},
}

var trafficSourceByAiSearchCardPreview = map[string]map[string]string{
	QueryRouterLogic: {
		conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
	},
	ChatHistoryLogic: {
		conf.ChatHistorySkip.ToConvert(): "true",
	},
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbBingRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSougouRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbQuarkRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSerperRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	ChatLogic: {
		conf.ChatDisable: "true",
	},
	StreamChatLogic: {
		conf.StreamChatDisableReferences: "true",
		conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
			ModelName: "virtual-llm-searchcard-online",
			MaxTokens: lo.ToPtr[int32](2048),
			Stop: []string{
				"<|im_end|>",
			},
			Temperature:       lo.ToPtr[float32](0.8),
			TopP:              lo.ToPtr[float32](0.9),
			TopK:              lo.ToPtr[int32](50),
			RepetitionPenalty: lo.ToPtr[float32](1.1),
			PresencePenalty:   nil,
			FrequencyPenalty:  nil,
			Stage:             proto.BusinessStage_GENERATION,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_TAB.String(),
			},
		}.ToJsonString(),
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			IsCustom:                    true,
			SystemPromptId:              "ai_search_card_system",
			SystemDefaultPromptTemplate: conf.PromptByAiSearchCardSystem,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v2", conf.PromptByQwenUser, ""),
				conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
				conf.NewChatMsgConfigByCustomQuery("ai_search_card_user", conf.PromptByAiSearchCardUser),
			},
		}.ToJsonString(),
	},
	SaveQueryResultLogic: {
		// 不开启预制词缓存，走全量缓存
		conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
	},
}

var trafficSourceByEntity = map[string]map[string]string{
	QueryDefinitionLogic: {
		conf.IsEnableLogic: "true",
	},
	ChatHistoryLogic: {
		conf.ChatHistorySkip.ToConvert(): "true",
	},
	QueryRouterLogic: {
		conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
	},
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbBingRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSougouRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbQuarkRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSerperRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	StreamChatLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
			ModelName:    "virtual-llm-entityword-online",
			IsReferences: true,
			CiteMaxCount: 5,
			MaxTokens:    lo.ToPtr[int32](2048),
			Stop: []string{
				"<|im_end|>",
			},
			Temperature:       lo.ToPtr[float32](0.8),
			TopP:              lo.ToPtr[float32](0.9),
			TopK:              lo.ToPtr[int32](50),
			RepetitionPenalty: lo.ToPtr[float32](1.1),
			PresencePenalty:   nil,
			FrequencyPenalty:  nil,
			Stage:             proto.BusinessStage_GENERATION,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_TAB.String(),
			},
		}.ToJsonString(),
	},
	SaveQueryResultLogic: {
		// 不开启预制词缓存，走全量缓存
		conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
	},
}

var trafficSourceByEntityPreview = map[string]map[string]string{
	QueryDefinitionLogic: {
		conf.IsEnableLogic: "true",
	},
	ChatHistoryLogic: {
		conf.ChatHistorySkip.ToConvert(): "true",
	},
	QueryRouterLogic: {
		conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
	},
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbBingRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSougouRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbQuarkRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSerperRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	ChatLogic: {
		conf.ChatDisable: "true",
	},
	StreamChatLogic: {
		conf.StreamChatDisableReferences: "true",
		conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
			ModelName:    "virtual-llm-entityword-online",
			IsReferences: true,
			CiteMaxCount: 5,
			MaxTokens:    lo.ToPtr[int32](2048),
			Stop: []string{
				"<|im_end|>",
			},
			Temperature:       lo.ToPtr[float32](0.8),
			TopP:              lo.ToPtr[float32](0.9),
			TopK:              lo.ToPtr[int32](50),
			RepetitionPenalty: lo.ToPtr[float32](1.1),
			PresencePenalty:   nil,
			FrequencyPenalty:  nil,
			Stage:             proto.BusinessStage_GENERATION,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_TAB.String(),
			},
		}.ToJsonString(),
	},
	SaveQueryResultLogic: {
		// 不开启预制词缓存，走全量缓存
		conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
	},
}

var trafficSourceByBelowBannerQuestion = map[string]map[string]string{
	ExtraAnswerCovertLogic: {
		conf.IsEnableLogic: "true",
	},
	ChatHistoryLogic: {
		conf.ChatHistorySkip.ToConvert(): "true",
	},
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbBingRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSougouRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbQuarkRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSerperRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	SaveQueryResultLogic: {
		// 不开启预制词缓存，走全量缓存
		conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
	},
}
