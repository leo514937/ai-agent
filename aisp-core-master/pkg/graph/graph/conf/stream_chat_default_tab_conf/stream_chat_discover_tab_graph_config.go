package stream_chat_default_tab_conf

import (
	"fmt"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	searchThrift "git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
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
	conf.RegisterLogicConfig(&ChatDiscoverTabLogicConfig{})
}

type ChatDiscoverTabLogicConfig struct {
	conf.LogicConfig
}

// GetGraphBizType 获取Graph 当前图名称
func (c *ChatDiscoverTabLogicConfig) GetGraphBizType() string {
	return conf.LogicConfigNameByDiscoverTab
}

// GetBizConfigMap 获取业务配置
func (c *ChatDiscoverTabLogicConfig) GetBizConfigMap() map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		CopyUserMetaLogic: {
			conf.ConfigApi: graph_constant.ApiStreamChat,
		},
		SecurityReviewLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
				Scene:           proto.ChatType_DISCOVER_TAB.String(),
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
					Temperature:           lo.ToPtr[float32](0),
					GuidedChoice: []macro.IntentionType{
						macro.GetQueryRouteIdentity(),
						macro.GetQueryRouteDirect(),
						macro.GetQueryRouteAuthor(),
						macro.GetQueryRouteSearch(),
						macro.GetQueryRouteMath(),
					},
					DefaultChoice: macro.GetQueryRouteSearch(),
				},
			),
		},
		BgeEmbeddingFetcherLogic: {
			conf.EmbeddingModelName: "bge-embedding-ai-zhida-online",
		},
		SecurityReviewMLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
				Scene:           proto.ChatType_DISCOVER_TAB.String(),
			}.ToJsonString(),
		},
		FaqMLogic: {
			conf.ConfigFaqSimilarityThreshold: "faq.embeddingSimilarityThreshold",
			conf.ConfigFaqKey:                 string(conf.SearchTabFAQ),
			conf.ConfigFaqMatchTypeKey:        conf.BuildConfigArrayValue(conf.FaqMatchTypeFullMatch.String(), conf.FaqMatchTypeKeywordMatchAll.String(), conf.FaqMatchTypeKeywordMatchAny.String(), conf.FaqMatchTypeEmbeddingSimilarity.String()),
			conf.EmbeddingModelName:           "bge-embedding-ai-zhida-online",
		},
		KbZhihuRecallLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				OrderGroup: 0,
				RecallSize: 16,
				Vertical:   []searchThrift.Vertical{searchThrift.Vertical_CONTENT},
			}),
		},
		KbBingRecallLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				OrderGroup: 1,
				RecallSize: 8,
			}),
			conf.BaseConfigSkip: "true",
		},
		KbQuarkRecallLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				OrderGroup: 2,
				RecallSize: 8,
			}),
		},
		KbSougouRecallLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				OrderGroup: 3,
				RecallSize: 0,
			}),
			conf.BaseConfigSkip: "true",
		},
		KbSerperRecallLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				OrderGroup: 4,
				RecallSize: 8,
			}),
			conf.BaseConfigSkip: "true",
		},
		KbOutSiteRumRecallLogic: {
			conf.ConfigRecallSize: "10",
		},
		KbOutSiteRuceneRecallLogic: {
			conf.ConfigRecallSize: "10",
		},
		AuthorSearchRecallLogic: {
			conf.BaseConfigSkip:   "true",
			conf.ConfigRecallSize: "100",
		},
		AuthorSearchSelfRecallLogic: {
			conf.BaseConfigSkip: "true",
		},
		KbSameQuestionAnswerAppendLogic: {
			conf.RecallSameQuestionAnswerTopK: "1",
		},
		AuthorSearchMergeLogic: {
			conf.AuthorSearchAgentRankBeta: "0.5",
			conf.RecallMergeTopK:           "8",
			conf.RecallMergeGuarantee:      "author_self:1",
			conf.RecallMergeScoreThreshold: "0.5",
		},
		KbRecallOutSiteSourceMergeLogic: {
			conf.RecallMergeTopK:           "4",
			conf.RecallMergeScoreThreshold: "0.95",
			conf.RecallMergeScoreTextField: enums.SimilarTextTypeByTitle.String(),
		},
		KbRecallZhihuSourceMergeLogic: {
			conf.RecallMergeTopK:           "100",
			conf.RecallMergeScoreThreshold: "0.7",
			conf.RecallMergeScoreTextField: enums.SimilarTextTypeByTitleAndContent2048.String(),
			conf.RecallMergeScoreSourceThreshold: strings.Join([]string{
				fmt.Sprintf("%s:%f", conf.KbSourceZhihuSameQuestionAnswer, 0.9),
			}, ";"),
		},
		RecallInsideFilterLogic: {
			conf.SummaryRecallFilterIo.ToConvert(): cast.ToString(true),
		},
		RecallOutsideFilterLogic: {
			conf.SummaryRecallFilterIo.ToConvert(): cast.ToString(false),
		},
		ValidContentRegulateFetcherLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				content.DocType_Answer.String(),
				content.DocType_Article.String(),
			}, ","),
			conf.ConfigRegulateSceneCode:    rpc.SceneCodeSearch,
			conf.ConfigRegulateSubSceneCode: rpc.SubSceneCodeDEFAULT,
		},
		ValidContentSecurityFetcherLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				content.DocType_Text.String(),
				content.DocType_Link.String(),
			}, ","),
		},
		ContentRegulateFilterLogic: {
			conf.ConfigRegulateKey: rpc.VisitorCirculate,
		},
		KbRecallSimhashFilterLogic: {
			conf.RecallFilterSimHashThreshold.ToConvert(): "0.96",
		},
		Recall2ModelChunkAndScoreLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
				KeySize:                    512,
				KeyStep:                    256,
				KeyOffset:                  0.5,
				ValueSize:                  1024,
				TotalSize:                  4096,
				ScoreThreshold:             0,
				BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
				ActualChunkSizeLimitPerDoc: 2048,
			}),
		},
		AgentOverwriteConfigLogic: {
			conf.OverwriteConfigBy: "agent",
		},
		AgentOverwriteConfigLogic2: {
			conf.OverwriteConfigBy: macro.AuthorSelf,
		},
		StreamChatLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
				ModelName:          "ds-v3-zhida-online",
				IsReferences:       false,
				CiteMaxCount:       5,
				ContextLength:      54 * 1024,
				ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
				MaxTokens:          lo.ToPtr[int32](8 * 1024),
				TopP:               lo.ToPtr[float32](0.8),
				Stage:              proto.BusinessStage_GENERATION,
				SecurityConfig: &conf.SecurityConfig{
					SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
					ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
					Scene:           proto.ChatType_DISCOVER_TAB.String(),
				},
			}.ToJsonString(),
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId:              "1306",
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
		KbRecallChunkAndReRankV2BeforeLogic: {
			conf.Answer2CardContentType: strings.Join([]string{content.DocType_Answer.String(), content.DocType_Article.String()}, ","),
		},
		RelevantQuerySecurityReviewLogic: {conf.RiskConfigWordSource.ToConvert(): proto.QueryType_RELATE_WORD_QUESTION.String()},
		SecurityReviewOutLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:         rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:            proto.ChatType_DISCOVER_TAB.String(),
				ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
			}.ToJsonString(),
		},
		TagCoreMetaFetcherLogic: {
			conf.TagCoreSceneCode:    string(rpc.SceneCode_AiUserInterest),
			conf.TagCoreAppGroupCode: string(rpc.AppGroupCode_AiUserRecall),
		},
	}
	return logicConfigMap
}

// GetAbParamMap 获取AB参数Map
// 把该 graph 涉及的实验的 base 组放到这里，用于打点
func (c *ChatDiscoverTabLogicConfig) GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue {
	return map[zlab.SceneId][]zlab.ZlabValue{
		macro.ZlabSceneIdAiRecDomain: {},
	}
}

func (c *ChatDiscoverTabLogicConfig) GetOverwriteStrategyId(agent string, exps ...string) string {
	return strings.Join(append([]string{agent}, exps...), "_")
}

func (c *ChatDiscoverTabLogicConfig) GetOverwriteBizConfigMap(strategyId string) map[string]map[string]string {
	return GetDefOverwriteStrategyId(strategyId)
}

func (c *ChatDiscoverTabLogicConfig) GetOverwriteBizConfigMapByTraffic(traffic proto.TrafficSource, client proto.ClientSource) map[string]map[string]string {
	return map[string]map[string]string{}
}
