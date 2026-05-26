package stream_chat_default_tab_conf

import (
	"encoding/json"
	"strings"

	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"github.com/samber/lo"
)

func GetDefOverwriteStrategyId(strategyId string) map[string]map[string]string {
	var subTag string
	var brandName string
	// 处理包含 subTag 的情况
	if strings.Contains(strategyId, "_") {
		subStrategyIds := strings.Split(strategyId, "_")
		if len(subStrategyIds) == 0 {
			return map[string]map[string]string{}
		}
		strategyId = subStrategyIds[0]
		if len(subStrategyIds) > 1 {
			subTag = subStrategyIds[1]
		}
		if len(subStrategyIds) > 2 {
			brandName = subStrategyIds[2]
		}
	}

	switch {
	case strategyId == macro.GetQueryRouteDirect().String() && subTag == macro.DeepThinking:
		return deepThinkingDirectlyAnswerAgentOverwriteLogicConfigMap
	case strategyId == macro.GetQueryRouteDirect().String():
		return directlyAnswerAgentOverwriteLogicConfigMap
	case strategyId == macro.GetQueryRouteIdentity().String() && subTag == macro.DeepThinking:
		return deepThinkingWhoAreYouAgentOverwriteLogicConfigMap
	case strategyId == macro.GetQueryRouteIdentity().String() && subTag == "":
		return whoAreYouAgentOverwriteLogicConfigMap // 普通 who are you
	case strategyId == macro.GetQueryRouteIdentity().String() && subTag == "gr":
		return whoAreYouGRAgentOverwriteLogicConfigMap // 政府关系 who are you
	case strategyId == macro.GetQueryRouteIdentity().String() && subTag == macro.ZplusBrand:
		return getWhoAreYouZplusAgentOverwriteLogicConfigMap(brandName) // zplus who are you
	//case strategyId == macro.GetQueryRouteMath().String():
	//	return mathConfigMap
	case strategyId == macro.GetQueryRouteCode().String() && subTag == macro.DeepThinking:
		return deepThinkingCodeConfigMap
	case strategyId == macro.GetQueryRouteCode().String():
		return codeConfigMap
	case strategyId == macro.GetQueryRouteAuthor().String():
		return authorAgentOverwriteLogicConfigMap
	case strategyId == macro.AuthorSelf:
		return authorSelfOverwriteLogicConfigMap
	case strategyId == macro.ReAnswerAuthorSelf:
		return authorAgentOverwriteLogicConfigMap
	case strategyId == macro.EmptyRecallNoChat:
		return emptyRecallConfigMap
	case strategyId == macro.DeepThinkingEmptyRecall:
		return deepThinkingEmptyRecallConfigMap
	case subTag == macro.ZplusBrand:
		return getZplusAgentOverwriteLogicConfigMap(brandName)
	default:
		return map[string]map[string]string{}
	}
}

// =====================================================================================================================
var directlyAnswerAgentOverwriteLogicConfigMap = map[string]map[string]string{
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbZhihuRecallLogic: {
		conf.BaseConfigSkip: "true",
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
	KbOutSiteRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbOutSiteRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbZPlusAutomotiveRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchSelfRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	StreamChatLogic: {
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zhida_direct_answer_summary_system",
			SystemDefaultPromptTemplate: conf.PromptByQwenSystem,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByQuery(),
			},
		}.ToJsonString(),
	},
}

var deepThinkingDirectlyAnswerAgentOverwriteLogicConfigMap = map[string]map[string]string{
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbZhihuRecallLogic: {
		conf.BaseConfigSkip: "true",
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
	KbOutSiteRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbOutSiteRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchSelfRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	StreamChatLogic: {
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zhida_summary_system_reasoning",
			SystemDefaultPromptTemplate: conf.PromptCoderQuery,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByKnowledge("zhida_summary_user_reasoning_emptyretrieval", conf.PromptByQwenUser, ""),
			},
		}.ToJsonString(),
	},
}

var whoAreYouAgentOverwriteLogicConfigMap = map[string]map[string]string{
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbZhihuRecallLogic: {
		conf.BaseConfigSkip: "true",
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
	KbOutSiteRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbOutSiteRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchSelfRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	StreamChatLogic: {
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zhida_whoareyou_summary_system",
			SystemDefaultPromptTemplate: conf.PromptByQwenSystem,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByKnowledge("zhida_whoareyou_summary_user", conf.PromptByQwenUser, ""),
			},
		}.ToJsonString(),
	},
}

var deepThinkingWhoAreYouAgentOverwriteLogicConfigMap = map[string]map[string]string{
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbZhihuRecallLogic: {
		conf.BaseConfigSkip: "true",
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
	KbOutSiteRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbOutSiteRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchSelfRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	StreamChatLogic: {
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zhida_summary_system_reasoning",
			SystemDefaultPromptTemplate: conf.PromptCoderQuery,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByKnowledge("zhida_summary_user_reasoning_emptyretrieval", conf.PromptByQwenUser, ""),
			},
		}.ToJsonString(),
	},
}

// 政府关系 who are you
var whoAreYouGRAgentOverwriteLogicConfigMap = map[string]map[string]string{
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbZhihuRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbBingRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbSougouRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbOutSiteRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbOutSiteRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchSelfRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	StreamChatLogic: {
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zhida_whoareyou_summary_system",
			SystemDefaultPromptTemplate: conf.PromptByQwenSystem,
			SystemPromptTag:             "gov_rel",
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByKnowledge("zhida_whoareyou_summary_user", conf.PromptByQwenUser, "gov_rel"),
			},
		}.ToJsonString(),
	},
}

func getWhoAreYouZplusAgentOverwriteLogicConfigMap(brandName string) map[string]map[string]string {
	promptTag := getBrandPromptTag(brandName)
	configMap := map[string]map[string]string{
		QueryMergeLogic: {
			conf.QueryMergeSkipAndSetAsQuery: "true",
		},
		KbZhihuRecallLogic: {
			conf.BaseConfigSkip: "true",
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
		KbOutSiteRumRecallLogic: {
			conf.BaseConfigSkip: "true",
		},
		KbOutSiteRuceneRecallLogic: {
			conf.BaseConfigSkip: "true",
		},
		KbZPlusAutomotiveRecallLogic: {
			conf.BaseConfigSkip: "true",
		},
		AuthorSearchRecallLogic: {
			conf.BaseConfigSkip: "true",
		},
		AuthorSearchSelfRecallLogic: {
			conf.BaseConfigSkip: "true",
		},
		StreamChatLogic: {
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId:              "zplus_whoareyou_summary_system",
				SystemDefaultPromptTemplate: conf.PromptByQwenSystem,
				SystemPromptTag:             getBrandPromptTag(brandName),
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
					conf.NewChatMsgConfigByKnowledge("zplus_whoareyou_summary_user", conf.PromptByQwenUser, promptTag),
				},
			}.ToJsonString(),
		},
	}
	return configMap
}

var authorAgentOverwriteLogicConfigMap = map[string]map[string]string{
	AuthorSearchRecallLogic: {
		conf.BaseConfigSkip: "false",
	},
	AuthorSearchSelfRecallLogic: {
		conf.BaseConfigSkip: "false",
	},
	StreamChatLogic: {
		conf.StreamChatDisableReferences: "true",
	},
	ChatLogic: {
		conf.ChatDisable: "true",
	},
	KbRecallChunkAndReRankV2BeforeLogic: {
		conf.Answer2CardEnableAuthorBge: "true",
	},
}

var authorSelfOverwriteLogicConfigMap = map[string]map[string]string{
	AuthorSearchRecallLogic: {
		conf.BaseConfigSkip: "false",
	},
	AuthorSearchSelfRecallLogic: {
		conf.BaseConfigSkip: "false",
	},
	StreamChatLogic: {
		conf.StreamChatDisableReferences: "true",
	},
	ChatLogic: {
		conf.ChatDisable: "true",
	},
	Recall2ModelReRankLogic: {
		conf.Answer2ModelOnlyAuthorSelf: "true",
	},
	KbRecallChunkAndReRankV2BeforeLogic: {
		conf.Answer2CardEnableAuthorBge: "true",
	},
}

var emptyRecallConfigMap = map[string]map[string]string{
	StreamChatLogic: {
		conf.ChatDisable: "true",
	},
}

var mathConfigMap = map[string]map[string]string{
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbZhihuRecallLogic: {
		conf.BaseConfigSkip: "true",
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
	KbOutSiteRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbOutSiteRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	AuthorSearchSelfRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	StreamChatLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
			ModelName:    "math-agents",
			IsReferences: true,
			MaxTokens:    lo.ToPtr[int32](2048),
			Stop: []string{
				"<|im_end|>",
				"[End]",
				"[end]",
				"\nReferences:\n",
				"\nSources:\n",
				"End.",
				"<s>",
				"</s>",
			},
			Temperature:       lo.ToPtr[float32](0.0),
			TopP:              lo.ToPtr[float32](1.0),
			PresencePenalty:   lo.ToPtr[float32](1.0),
			RepetitionPenalty: lo.ToPtr[float32](0.8),
			FrequencyPenalty:  nil,
			Stage:             proto.BusinessStage_GENERATION,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_TAB.String(),
			},
		}.ToJsonString(),
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zhida_math_query_system",
			SystemDefaultPromptTemplate: conf.PromptByMathQuery,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByQuery(),
			},
		}.ToJsonString(),
	},
}

var codeConfigMap = map[string]map[string]string{
	StreamChatLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
			ModelName:    "code-search",
			IsReferences: true,
			MaxTokens:    lo.ToPtr[int32](2048),
			Stop: []string{
				"<|im_end|>",
				"[End]",
				"[end]",
				"\nReferences:\n",
				"\nSources:\n",
				"End.",
				"<s>",
				"</s>",
			},
			Temperature:       lo.ToPtr[float32](0.0),
			TopP:              lo.ToPtr[float32](1.0),
			PresencePenalty:   lo.ToPtr[float32](1.0),
			RepetitionPenalty: lo.ToPtr[float32](1.2),
			Stage:             proto.BusinessStage_GENERATION,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_TAB.String(),
			},
		}.ToJsonString(),
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zhida_code_query_system",
			SystemDefaultPromptTemplate: conf.PromptCoderQuery,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v2", conf.PromptByQwenUser, ""),
				conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByQuery(),
			},
		}.ToJsonString(),
	},
}

var deepThinkingCodeConfigMap = map[string]map[string]string{
	StreamChatLogic: {
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zhida_summary_system_reasoning",
			SystemDefaultPromptTemplate: conf.PromptCoderQuery,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByKnowledge("zhida_summary_user_reasoning", conf.PromptByQwenUser, ""),
			},
		}.ToJsonString(),
	},
}

var deepThinkingEmptyRecallConfigMap = map[string]map[string]string{
	StreamChatLogic: {
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zhida_summary_system_reasoning",
			SystemDefaultPromptTemplate: conf.PromptCoderQuery,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByKnowledge("zhida_summary_user_reasoning_emptyretrieval", conf.PromptByQwenUser, ""),
			},
		}.ToJsonString(),
	},
}

func getZplusAgentOverwriteLogicConfigMap(brandName string) map[string]map[string]string {
	if "辟谣助手" == brandName {
		return refuteRumorsMap
	}
	promptTag := getBrandPromptTag(brandName)
	configMap := map[string]map[string]string{
		StreamChatLogic: {
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId:              "zplus_summary_system_elaborated",
				SystemDefaultPromptTemplate: conf.PromptByQwenSystem,
				SystemPromptTag:             promptTag,
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v2", conf.PromptByQwenUser, ""),
					conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
					conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
					conf.NewChatMsgConfigByQuery(),
				},
			}.ToJsonString(),
		},
	}
	return configMap
}

var refuteRumorsMap = map[string]map[string]string{
	SecurityReviewLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceZplusRumorsQuery.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
			Scene:           proto.ChatType_ZPLUS_BRAND.String(),
		}.ToJsonString(),
	},
	SecurityReviewMLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceZplusRumorsQuery.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
			Scene:           proto.ChatType_ZPLUS_BRAND.String(),
		}.ToJsonString(),
	},
	StreamChatLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
			ModelName:    entities.ZplusQwen110B,
			IsReferences: true,
			CiteMaxCount: 5,
			MaxTokens:    lo.ToPtr[int32](2048),
			Stop: []string{
				"<|im_end|>",
				"[End]",
				"[end]",
				"\nReferences:\n",
				"\nSources:\n",
				"End.",
				"<s>",
				"</s>",
			},
			Temperature:      lo.ToPtr[float32](0.3),
			TopP:             lo.ToPtr[float32](0.3),
			PresencePenalty:  lo.ToPtr[float32](0.5),
			FrequencyPenalty: nil,
			Stage:            proto.BusinessStage_GENERATION,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceZplusRumorsAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZPLUS_BRAND.String(),
			},
		}.ToJsonString(),
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId:              "zplus_summary_system_elaborated",
			SystemDefaultPromptTemplate: conf.PromptByQwenSystem,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v2", conf.PromptByQwenUser, ""),
				conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByQuery(),
			},
		}.ToJsonString(),
	},
	SecurityReviewOutLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
			SourceId:         rpc.RiskCheckSourceZplusRumorsAnswer.ToConvert(),
			ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:            proto.ChatType_ZPLUS_BRAND.String(),
			ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
		}.ToJsonString(),
	},
}

func getBrandPromptTag(brandName string) string {
	configStr := config.GetStringByNamespace(macro.ZplusApolloNamespace, macro.BrandPromptTag, "")
	if configStr == "" {
		return ""
	}
	var brandName2PromptTagMap map[string]string
	err := json.Unmarshal([]byte(configStr), &brandName2PromptTagMap)
	if err != nil {
		return ""
	}
	promptTag, ok := brandName2PromptTagMap[brandName]
	if !ok {
		return ""
	}
	return promptTag
}
