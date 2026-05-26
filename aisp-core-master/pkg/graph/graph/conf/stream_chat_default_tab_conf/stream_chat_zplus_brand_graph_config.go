package stream_chat_default_tab_conf

import (
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank/rerank_util"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

func init() {
	conf.RegisterLogicConfig(&ChatZplusBrandLogicConfig{})
}

type ChatZplusBrandLogicConfig struct {
	conf.LogicConfig
}

// GetGraphBizType 获取Graph 当前图名称
func (c *ChatZplusBrandLogicConfig) GetGraphBizType() string {
	return conf.LogicConfigNameByZplusBrand
}

// GetBizConfigMap 获取业务配置
func (c *ChatZplusBrandLogicConfig) GetBizConfigMap() map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		CopyUserMetaLogic: {
			conf.ConfigApi: graph_constant.ApiStreamChat,
		},
		SecurityReviewLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceZplusBrandQuery.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
				Scene:           proto.ChatType_ZPLUS_BRAND.String(),
			}.ToJsonString(),
		},
		AnswerSecurityBeforePostLogic: {
			conf.IsNotAllowReviseSecurityResult.ToConvert(): cast.ToString(true),
		},
		FaqLogic: {
			conf.ConfigFaqSimilarityThreshold: "faq.embeddingSimilarityThreshold",
			conf.ConfigFaqKey:                 string(conf.SearchTabFAQ),
			conf.ConfigFaqMatchTypeKey:        conf.BuildConfigArrayValue(conf.FaqMatchTypeKeywordMatchAll.String(), conf.FaqMatchTypeKeywordMatchAny.String(), conf.FaqMatchTypeEmbeddingSimilarity.String(), conf.FaqMatchTypeFullMatch.String()),
			conf.EmbeddingModelName:           "bge-embedding-ai-zhida-online",
			conf.BaseConfigSkip:               "true",
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
					MaxTokens:             lo.ToPtr[int32](32),
					Timeout:               5 * time.Second,
					Temperature:           lo.ToPtr[float32](0.0),
					GuidedChoice: []macro.IntentionType{
						macro.GetQueryRouteIdentity(),
						macro.GetQueryRouteDirect(),
						macro.GetQueryRouteSearch(),
					},
					RouteBiz:      "ad-brand-qa",
					DefaultChoice: macro.GetQueryRouteSearch(),
				},
			),
		},
		SecurityReviewMLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceZplusBrandQuery.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
				Scene:           proto.ChatType_ZPLUS_BRAND.String(),
			}.ToJsonString(),
		},
		FaqMLogic: {
			conf.ConfigFaqSimilarityThreshold: "faq.embeddingSimilarityThreshold",
			conf.ConfigFaqKey:                 string(conf.SearchTabFAQ),
			conf.ConfigFaqMatchTypeKey:        conf.BuildConfigArrayValue(conf.FaqMatchTypeFullMatch.String(), conf.FaqMatchTypeKeywordMatchAll.String(), conf.FaqMatchTypeKeywordMatchAny.String(), conf.FaqMatchTypeEmbeddingSimilarity.String()),
			conf.EmbeddingModelName:           "bge-embedding-ai-zhida-online",
			conf.BaseConfigSkip:               "true",
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
		KbZPlusAutomotiveRecallLogic: {
			conf.ConfigRecallSize: "8",
		},
		RecallInsideFilterLogic: {
			conf.SummaryRecallFilterIo.ToConvert(): cast.ToString(true),
		},
		RecallOutsideFilterLogic: {
			conf.SummaryRecallFilterIo.ToConvert(): cast.ToString(false),
		},
		ValidContentRegulateFetcherLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				aiContent.DocType_Answer.String(),
				aiContent.DocType_Article.String(),
			}, ","),
			conf.ConfigRegulateSceneCode:    rpc.SceneCommercialCodeSearch,
			conf.ConfigRegulateSubSceneCode: rpc.SubSceneCodeDEFAULT,
		},
		ValidContentSecurityFetcherLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				aiContent.DocType_Text.String(),
				aiContent.DocType_Link.String(),
			}, ","),
		},
		KbRecallChunkAndReRankV2BeforeLogic: {
			conf.Answer2CardContentType: strings.Join([]string{
				aiContent.DocType_Answer.String(),
				aiContent.DocType_Article.String(),
				aiContent.DocType_Pin.String(),
				aiContent.DocType_ZVideo.String(),
			}, ","),
		},
		ContentRegulateFilterLogic: {
			conf.ConfigRegulateKey: rpc.VisitorCirculate,
		},
		KbRecallSimhashFilterLogic: {
			conf.RecallFilterSimHashThreshold.ToConvert(): "0.96",
		},
		BgeEmbeddingFetcherLogic: {
			conf.EmbeddingModelName: "bge-embedding-ai-zhida-online",
		},
		Recall2ModelChunkAndScoreLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
				KeySize:                    512,
				KeyStep:                    256,
				KeyOffset:                  0.5,
				ValueSize:                  1024,
				TotalSize:                  4096,
				ScoreThreshold:             0.1,
				BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
				UseRaw:                     true,
				ActualChunkSizeLimitPerDoc: 2048,
			}),
		},

		AgentOverwriteConfigLogic: {
			conf.OverwriteConfigBy:       "agent",
			conf.OverwriteConfigStrategy: "zplus",
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
					SourceId:        rpc.RiskCheckSourceZplusBrandAnswer.ToConvert(),
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
		ChatLogic: {
			conf.ChatDisable: "true",
		},
		RelevantQuerySecurityReviewLogic: {conf.RiskConfigWordSource.ToConvert(): proto.QueryType_RELATE_WORD_QUESTION.String()},
		SecurityReviewOutLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:         rpc.RiskCheckSourceZplusBrandAnswer.ToConvert(),
				ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:            proto.ChatType_ZPLUS_BRAND.String(),
				ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
			}.ToJsonString(),
		},
	}

	return logicConfigMap
}

func (c *ChatZplusBrandLogicConfig) GetOverwriteStrategyId(agent string, exps ...string) string {
	return strings.Join(append([]string{agent}, exps...), "_")
}
func (c *ChatZplusBrandLogicConfig) GetOverwriteBizConfigMap(strategyId string) map[string]map[string]string {
	return GetDefOverwriteStrategyId(strategyId)
}

func (c *ChatZplusBrandLogicConfig) GetOverwriteBizConfigMapByTraffic(traffic proto.TrafficSource, client proto.ClientSource) map[string]map[string]string {
	return map[string]map[string]string{}
}

// GetAbParamMap 获取AB参数Map
// 把该 graph 涉及的实验的 base 组放到这里，用于打点
func (c *ChatZplusBrandLogicConfig) GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue {
	return map[zlab.SceneId][]zlab.ZlabValue{
		macro.ZlabSceneIdAiRecDomain: {},
	}
}
