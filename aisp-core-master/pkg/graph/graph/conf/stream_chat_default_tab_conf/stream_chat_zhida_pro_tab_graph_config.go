package stream_chat_default_tab_conf

import (
	"fmt"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content_biz_ext/paper_biz_ext"
	searchThrift "git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank/rerank_util"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

func init() {
	conf.RegisterLogicConfig(&ChatZhidaProTabLogicConfig{})
}

type ChatZhidaProTabLogicConfig struct {
	conf.LogicConfig
}

// GetGraphBizType 获取Graph 当前图名称
func (c *ChatZhidaProTabLogicConfig) GetGraphBizType() string {
	return conf.LogicConfigNameByZhiDaProTab
}

// GetBizConfigMap 获取业务配置
func (c *ChatZhidaProTabLogicConfig) GetBizConfigMap() map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		CopyUserMetaLogic: {
			conf.ConfigApi: graph_constant.ApiStreamChat,
		},
		SecurityReviewLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_PRO_TAB.String(),
			}.ToJsonString(),
		},
		RequestLegalityLogic: {
			conf.RequestLegalityRule: strings.Join([]string{macro.IsBlockedUser, macro.IsUserQpsOverLimit, macro.IsNotHasKbOrPersonalKbOrDoc}, ","),
		},
		AnswerSecurityBeforePostLogic: {
			conf.IsNotAllowReviseSecurityResult.ToConvert(): cast.ToString(true),
		},
		FaqLogic: {
			conf.ConfigFaqSimilarityThreshold: "faq.embeddingSimilarityThreshold",
			conf.ConfigFaqKey:                 string(conf.SearchTabFAQ),
			conf.ConfigFaqMatchTypeKey:        conf.BuildConfigArrayValue(conf.FaqMatchTypeKeywordMatchAll.String(), conf.FaqMatchTypeKeywordMatchAny.String(), conf.FaqMatchTypeEmbeddingSimilarity.String(), conf.FaqMatchTypeFullMatch.String()),
			conf.EmbeddingModelName:           "bge-embedding-ai-zhida-online",
		},
		QueryMergeLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
				ModelName:     "query-merger-ai-zhida-online",
				ContextLength: 8 * 1024,
				MaxTokens:     lo.ToPtr[int32](1024),
				Stop: []string{
					"<|im_end|>",
					"<|endoftext|>",
				},
				TopP:             lo.ToPtr[float32](0.8),
				Temperature:      lo.ToPtr[float32](0.5),
				PresencePenalty:  lo.ToPtr[float32](0.5),
				FrequencyPenalty: lo.ToPtr[float32](0.0),
				Stage:            proto.BusinessStage_QUERY_MERGE,
			}.ToJsonString(),
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId: "1304",
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByChatHistoryAndLimit(ChatHistoryNewLimit, 5*1024),
					conf.NewChatMsgConfigByCustomQuery("1309", ""),
				},
			}.ToJsonString(),
		},
		QueryRouterLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(
				conf.RouteConfig{
					IsEnable:              true,
					ModelName:             entities.QueryRouter,
					SystemPromptKey:       "zhida_query_router_system_prompt",
					SystemPrompt:          conf.PromptByQueryRouterSystem,
					QueryPromptKey:        "zhida_query_router_query_prompt",
					QueryPrompt:           conf.PromptByQueryRouterQuery,
					IsNeedHistory:         true,
					ChatHistoryRoundLimit: 6,
					MaxTokens:             lo.ToPtr[int32](10),
					Timeout:               5 * time.Second,
					Temperature:           lo.ToPtr[float32](0.0),
					GuidedChoice: []macro.IntentionType{
						macro.GetQueryRouteIdentity(),
						macro.GetQueryRouteDirect(),
						macro.GetQueryRouteAuthor(),
						macro.GetQueryRouteSearch(),
						macro.GetQueryRouteMath(),
						macro.GetQueryRouteCode(),
					},
					DefaultChoice: macro.GetQueryRouteSearch(),
				},
			),
		},
		SecurityReviewMLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_PRO_TAB.String(),
			}.ToJsonString(),
		},
		FaqMLogic: {
			conf.ConfigFaqSimilarityThreshold: "faq.embeddingSimilarityThreshold",
			conf.ConfigFaqKey:                 string(conf.SearchTabFAQ),
			conf.ConfigFaqMatchTypeKey:        conf.BuildConfigArrayValue(conf.FaqMatchTypeFullMatch.String(), conf.FaqMatchTypeKeywordMatchAll.String(), conf.FaqMatchTypeKeywordMatchAny.String(), conf.FaqMatchTypeEmbeddingSimilarity.String()),
			conf.EmbeddingModelName:           "bge-embedding-ai-zhida-online",
		},
		BgeEmbeddingFetcherLogic: {
			conf.EmbeddingModelName: "bge-embedding-ai-zhida-online",
		},
		BgeM3EmbeddingFetcherLogic: {
			conf.EmbeddingModelName: "bge-m3-common-for-zhida-online",
			conf.EmbeddingType:      conf.EmbeddingTypeByBgeM3,
		},
		KbZhihuRecallLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				Vertical:   []searchThrift.Vertical{searchThrift.Vertical_CONTENT, searchThrift.Vertical_DomesticScholar, searchThrift.Vertical_ForeignScholar},
				OrderGroup: 0,
				RecallSize: 16,
				OnlyA4p:    true,
			}),
		},
		KbArxivRecallLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				Vertical:   []searchThrift.Vertical{searchThrift.Vertical_ForeignScholar},
				OrderGroup: 0,
				RecallSize: 0,
				OnlyA4p:    true,
			}),
		},
		KbReplenishArxivRecallLogic: {
			conf.ConfigRecallSize: "0",
			conf.BaseConfigSkip:   "true",
		},
		KbZhWikiRumRecallLogic: {
			conf.ConfigRecallSize: "0",
		},
		KbEnWikiRumRecallLogic: {
			conf.ConfigRecallSize: "0",
		},
		KbZhWikiRuceneRecallLogic: {
			conf.ConfigRecallSize: "0",
		},
		KbEnWikiRuceneRecallLogic: {
			conf.ConfigRecallSize: "0",
		},
		PersonalKnowledgeBaseRumRecallLogic: {
			conf.ConfigRecallSize: "0",
		},
		PersonalKnowledgeBaseRuceneRecallLogic: {
			conf.ConfigRecallSize: "0",
		},
		KbRecallZhihuSourceMergeLogic: {
			conf.RecallMergeTopK:           "100",
			conf.RecallMergeScoreThreshold: "0.0",
			conf.RecallMergeScoreSourceThreshold: strings.Join([]string{
				fmt.Sprintf("%s:%f", conf.KbSourceEnWikiRum, 0.6),
				fmt.Sprintf("%s:%f", conf.KbSourceZhWikiRum, 0.6),
				fmt.Sprintf("%s:%f", conf.KbSourceEnWikiRucene, 0.6),
				fmt.Sprintf("%s:%f", conf.KbSourceZhWikiRucene, 0.6),
			}, ";"),
			conf.RecallMergeScoreTextField: enums.SimilarTextTypeByTitleAndContent2048.String(),
			conf.RecallMergeScoreTextSourceField: strings.Join([]string{
				fmt.Sprintf("%s:%s", conf.KbSourceZhihuArxiv, enums.SimilarTextTypeByTitleAndAbstract.String()),
				fmt.Sprintf("%s:%s", conf.KbSourceZhihuWeipu, enums.SimilarTextTypeByTitleAndAbstract.String()),
				fmt.Sprintf("%s:%s", conf.PersonalKnowledgeBaseRum, enums.SimilarTextTypeByTitleAndContent2048.String()),
				fmt.Sprintf("%s:%s", conf.PersonalKnowledgeBaseRucene, enums.SimilarTextTypeByTitleAndContent2048.String()),
			}, ";"),
			conf.RecallMergeSortMethodField: util.Int2String(int(conf.SortMethodSourceOrder)),
			conf.RecallMergeSourceOrderField: strings.Join([]string{
				conf.KbSourceZhihuWeipu.String(),
				conf.KbSourceZhihuArxiv.String(),
				conf.KbSourceZhihu.String(),
			}, ","),
		},
		PersonalKnowledgeBaseMergeLogic: {
			conf.RecallMergeTopK:            "16",
			conf.RecallMergeScoreThreshold:  "0.0",
			conf.RecallMergeScoreTextField:  enums.SimilarTextTypeByTitleAndContent2048.String(),
			conf.RecallMergeSortMethodField: util.Int2String(int(conf.SortMethodSourceOrder)),
		},
		KbRecallFinalSourceMergeLogic: {
			conf.RecallMergeTopK:           "100",
			conf.RecallMergeScoreThreshold: "0.01",
			// 目前先全部为 0.01过滤 title，后续根据实际情况调整
			//conf.RecallMergeScoreSourceThreshold: strings.Join([]string{
			//	fmt.Sprintf("%s:%f", conf.PersonalKnowledgeBaseRucene, 0.0),
			//	fmt.Sprintf("%s:%f", conf.PersonalKnowledgeBaseRum, 0.0),
			//}, ";"),
			conf.RecallMergeScoreTextField:  enums.SimilarTextTypeByTitle.String(),
			conf.RecallMergeSortMethodField: util.Int2String(int(conf.SortMethodSimilarScore)),
		},
		ValidContentRegulateFetcherLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				aiContent.DocType_Answer.String(),
				aiContent.DocType_Article.String(),
				aiContent.DocType_Paper.String(),
				aiContent.DocType_Webpage.String(),
				aiContent.DocType_ZhiDaUserUpload.String(),
				aiContent.DocType_InternalDoc.String(),
			}, ","),
			conf.ConfigRegulateSceneCode:    rpc.SceneCodeSearch,
			conf.ConfigRegulateSubSceneCode: rpc.SubSceneCodeDEFAULT,
		},
		ContentRegulateFilterLogic: {
			conf.ConfigRegulateKey: rpc.VisitorCirculate,
		},
		KbRecallSimhashFilterLogic: {
			conf.RecallFilterSimHashThreshold.ToConvert(): "0.96",
		},
		RecallSecurityValidContentFetcherLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				aiContent.DocType_Paper.String(),
				aiContent.DocType_Webpage.String(),
				aiContent.DocType_Text.String(),
				aiContent.DocType_Link.String(),
				aiContent.DocType_InternalDoc.String(),
			}, ","),
			conf.FilterLogicConfByIncludePaperArr: strings.Join([]string{
				paper_biz_ext.PaperPublishSource_Arxiv.String(),
			}, ","),
			// 附加排除 当 IncludeDocType 和 ExtraExcludeKbSource 同时满足时 附加排除kbSource
			conf.FilterLogicConfByExtraExcludeKbSourceArr: strings.Join([]string{
				conf.KbSourceUserSpecified.String(),
			}, ","),
			conf.FilterLogicConfByIsCheckFullContent: "true",
		},
		KbRecallChunkCiteLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				aiContent.DocType_Answer.String(),
				aiContent.DocType_Article.String(),
				aiContent.DocType_Link.String(),
				aiContent.DocType_ZhiDaUserUpload.String(),
				aiContent.DocType_Paper.String(),
				aiContent.DocType_Webpage.String(),
				aiContent.DocType_InternalDoc.String(),
			}, ","),
		},
		Recall2ModelChunkAndScoreLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
				KeySize:                    512,
				KeyStep:                    256,
				KeyOffset:                  0.5,
				ValueSize:                  1024,
				TotalSize:                  10240,
				ScoreThreshold:             0.1,
				BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
				ActualChunkSizeLimitPerDoc: 2048,
			}),
		},

		StreamChatLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
				ModelName:          "ds-v3-zhida-online",
				IsReferences:       true,
				CiteMaxCount:       5,
				ContextLength:      54 * 1024,
				ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
				MaxTokens:          lo.ToPtr[int32](8 * 1024),
				TopP:               lo.ToPtr[float32](0.8),
				Stage:              proto.BusinessStage_GENERATION,
				SecurityConfig: &conf.SecurityConfig{
					SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
					ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
					Scene:           proto.ChatType_ZHIDA_PRO_TAB.String(),
				},
			}.ToJsonString(),
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId: "zhida_summary_system_elaborated",
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v2", conf.PromptByQwenUser, ""),
					conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
					conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
					conf.NewChatMsgConfigByQuery(),
				},
			}.ToJsonString(),
		},
		ChatLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
				ModelName: "question-gen-14b",
				MaxTokens: lo.ToPtr[int32](128),
				Stop: []string{
					"<|im_end|>",
					"<|endoftext|>",
				},
				TopP:             lo.ToPtr[float32](0.8),
				Temperature:      lo.ToPtr[float32](0.5),
				PresencePenalty:  lo.ToPtr[float32](0.5),
				FrequencyPenalty: lo.ToPtr[float32](0.0),
				Stage:            proto.BusinessStage_RELEVANT_QUERY,
			}.ToJsonString(),
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId: "1304",
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByKnowledge("1303", conf.PromptByRelevantQuery, ""),
				},
			}.ToJsonString(),
		},
		AgentOverwriteConfigLogic: {
			conf.OverwriteConfigBy: "agent",
		},
		AgentOverwriteConfigLogic2: {
			conf.OverwriteConfigBy: macro.EmptyRecall,
		},
		RelevantQuerySecurityReviewLogic: {conf.RiskConfigWordSource.ToConvert(): proto.QueryType_RELATE_WORD_QUESTION.String()},
		SecurityReviewOutLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:         rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:            proto.ChatType_ZHIDA_PRO_TAB.String(),
				ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
			}.ToJsonString(),
		},
		SaveQueryResultLogic: {
			// 默认只开启预制词缓存
			conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
		},
		TagCoreMetaFetcherLogic: {
			conf.TagCoreSceneCode:    string(rpc.SceneCode_AiUserInterest),
			conf.TagCoreAppGroupCode: string(rpc.AppGroupCode_AiUserRecall),
		},
	}

	return logicConfigMap
}
func (c *ChatZhidaProTabLogicConfig) GetOverwriteBizConfigMap(strategyId string) map[string]map[string]string {
	var subTag string

	// 处理包含 subTag 的情况
	if strings.Contains(strategyId, "_") {
		if strings.HasPrefix(strategyId, "zplus_summary_system") {
			subTag = "zplus_prompt"
		} else {
			subStrategyIds := strings.Split(strategyId, "_")
			if len(subStrategyIds) == 0 {
				return map[string]map[string]string{}
			}
			strategyId = subStrategyIds[0]
			if len(subStrategyIds) > 1 {
				subTag = subStrategyIds[1]
			}
		}
	}

	switch {
	case strategyId == macro.GetQueryRouteDirect().String() && subTag == macro.DeepThinking:
		return deepThinkingDirectlyAnswerAgentOverwriteLogicConfigMap
	case strategyId == macro.GetQueryRouteDirect().String():
		return directlyAnswerAgentOverwriteLogicConfigMapByPro
	case strategyId == macro.GetQueryRouteIdentity().String():
		return whoAreYouAgentOverwriteLogicConfigMapByPro
	case strategyId == macro.GetQueryRouteIdentity().String() && subTag == macro.DeepThinking:
		return deepThinkingWhoAreYouAgentOverwriteLogicConfigMap
	//case macro.GetQueryRouteMath().String():
	//	return mathConfigMapByPro
	case strategyId == macro.GetQueryRouteCode().String() && subTag == macro.DeepThinking:
		return deepThinkingCodeConfigMap
	case strategyId == macro.GetQueryRouteCode().String():
		return codeConfigMapByPro
	case strategyId == macro.EmptyRecallNoChat:
		return emptyRecallConfigMap
	case strategyId == macro.DeepThinkingEmptyRecall:
		return deepThinkingEmptyRecallConfigMap
	default:
		return map[string]map[string]string{}
	}
}

func (c *ChatZhidaProTabLogicConfig) GetOverwriteBizConfigMapByTraffic(traffic proto.TrafficSource, client proto.ClientSource) map[string]map[string]string {
	return map[string]map[string]string{}
}

func (c *ChatZhidaProTabLogicConfig) GetOverwriteStrategyId(agent string, exps ...string) string {
	return strings.Join(append([]string{agent}, exps...), "_")
}

// GetAbParamMap 获取AB参数Map
// 把该 graph 涉及的实验的 base 组放到这里，用于打点
func (c *ChatZhidaProTabLogicConfig) GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue {
	return map[zlab.SceneId][]zlab.ZlabValue{
		macro.ZlabSceneIdWebStandardDomain: {},
	}
}

//  =========== 以下为 TrafficSourceOverwriteLogicConfigMap ===========

var SpecifiedMultDocOverwriteLogicConfigMapByPro = map[string]map[string]string{
	Recall2ModelChunkAndScoreLogic: Recall2ModelChunkSize,
	StreamChatLogic: {
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId: "specified_doc_system",
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByKnowledge("specified_doc_user", "", ""),
			},
		}.ToJsonString(),
	},
}

var Recall2ModelChunkSize = map[string]string{
	conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
		KeySize:                    512,
		KeyStep:                    256,
		KeyOffset:                  0.5,
		ValueSize:                  1024,
		TotalSize:                  10240,
		ScoreThreshold:             0.1,
		BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
		EachDocHasChunk:            true,
		ActualChunkSizeLimitPerDoc: 2048,
	}),
}

var Recall2ModelChunkR1Size = map[string]string{
	conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
		KeySize:                    512,
		KeyStep:                    256,
		KeyOffset:                  0.5,
		ValueSize:                  1024,
		TotalSize:                  54 * 1024,
		ScoreThreshold:             0.1,
		BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
		EachDocHasChunk:            true,
		ActualChunkSizeLimitPerDoc: 2048,
	}),
}

var Recall2ModelChunkSmallSingleSize = map[string]string{
	conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
		KeySize:                    512,
		KeyStep:                    256,
		KeyOffset:                  0.5,
		ValueSize:                  1024,
		TotalSize:                  10240,
		ScoreThreshold:             0.1,
		BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
		IsAllowSingleItemSkipChunk: true,
		ActualChunkSizeLimitPerDoc: 2048,
	}),
}

var Recall2ModelChunkSmallSingleR1Size = map[string]string{
	conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
		KeySize:                    512,
		KeyStep:                    256,
		KeyOffset:                  0.5,
		ValueSize:                  1024,
		TotalSize:                  54 * 1024,
		ScoreThreshold:             0.1,
		BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
		IsAllowSingleItemSkipChunk: true,
		ActualChunkSizeLimitPerDoc: 2048,
	}),
}

var SpecifiedSingleDocOverwriteLogicConfigMapByPro = map[string]map[string]string{
	Recall2ModelChunkAndScoreLogic: Recall2ModelChunkSmallSingleSize,
	StreamChatLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
			ModelName:          "ds-v3-zhida-online",
			IsReferences:       true,
			CiteMaxCount:       1,
			ContextLength:      54 * 1024,
			ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
			MaxTokens:          lo.ToPtr[int32](8 * 1024),
			TopP:               lo.ToPtr[float32](0.8),
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_PRO_TAB.String(),
			},
			Stage: proto.BusinessStage_GENERATION,
		}.ToJsonString(),
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId: "specified_doc_system",
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByKnowledge("specified_doc_user", "", ""),
			},
		}.ToJsonString(),
		conf.StreamChatIsCitePage: "true",
	},
}

var SpecifiedBigSingleDocOverwriteLogicConfigMapByPro = map[string]map[string]string{
	Recall2ModelChunkAndScoreLogic: Recall2ModelChunkSize,
	StreamChatLogic: {
		conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
			ModelName:          "ds-v3-zhida-online",
			IsReferences:       true,
			CiteMaxCount:       1,
			ContextLength:      54 * 1024,
			ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
			MaxTokens:          lo.ToPtr[int32](8 * 1024),
			TopP:               lo.ToPtr[float32](0.8),
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_PRO_TAB.String(),
			},
			Stage: proto.BusinessStage_GENERATION,
		}.ToJsonString(),
		conf.ChatMessageJsonConfig: conf.MsgConfig{
			SystemPromptId: "specified_doc_system",
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(ChatHistoryLimit),
				conf.NewChatMsgConfigByKnowledge("specified_doc_user", "", ""),
			},
		}.ToJsonString(),
		conf.StreamChatIsCitePage: "true",
	},
}

var mathConfigMapByPro = map[string]map[string]string{
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbZhihuRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbArxivRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbReplenishArxivRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbZhWikiRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbEnWikiRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbZhWikiRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbEnWikiRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	PersonalKnowledgeBaseRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	PersonalKnowledgeBaseRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	SpecifiedDocRecallLogic: {
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
			Stage:             proto.BusinessStage_GENERATION,
			SecurityConfig: &conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_PRO_TAB.String(),
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

var codeConfigMapByPro = map[string]map[string]string{
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
				Scene:           proto.ChatType_ZHIDA_PRO_TAB.String(),
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

var whoAreYouAgentOverwriteLogicConfigMapByPro = map[string]map[string]string{
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbZhihuRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbArxivRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbReplenishArxivRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbZhWikiRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbEnWikiRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbZhWikiRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbEnWikiRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	PersonalKnowledgeBaseRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	PersonalKnowledgeBaseRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	SpecifiedDocRecallLogic: {
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

var directlyAnswerAgentOverwriteLogicConfigMapByPro = map[string]map[string]string{
	QueryMergeLogic: {
		conf.QueryMergeSkipAndSetAsQuery: "true",
	},
	KbZhihuRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbArxivRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbReplenishArxivRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbZhWikiRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbEnWikiRumRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbZhWikiRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	KbEnWikiRuceneRecallLogic: {
		conf.BaseConfigSkip: "true",
	},
	SpecifiedDocRecallLogic: {
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
