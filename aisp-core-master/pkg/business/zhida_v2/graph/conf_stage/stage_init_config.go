package conf_stage

import (
	"context"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

type StageInitConfig struct {
	stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
}

func (c *StageInitConfig) GetConfigMap(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		stream_chat_default_tab_conf.CopyUserMetaLogic: {
			conf.ConfigApi: graph_constant.ApiStreamChat,
		},
		stream_chat_default_tab_conf.RequestLegalityLogic: {
			conf.RequestLegalityRule: strings.Join([]string{macro.IsBlockedUser, macro.IsUserQpsOverLimit}, ","),
		},
		stream_chat_default_tab_conf.KnowledgeBaseInfoLogic: {
			conf.ConfigLimit: "20",
		},
		stream_chat_default_tab_conf.SecurityReviewLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_V2.String(),
			}.ToJsonString(),
		},
		stream_chat_default_tab_conf.SecurityReviewMLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_V2.String(),
			}.ToJsonString(),
		},
		stream_chat_default_tab_conf.FaqLogic: {
			conf.ConfigFaqSimilarityThreshold: "faq.embeddingSimilarityThreshold",
			conf.ConfigFaqKey:                 string(conf.SearchTabFAQ),
			conf.ConfigFaqMatchTypeKey:        conf.BuildConfigArrayValue(conf.FaqMatchTypeKeywordMatchAll.String(), conf.FaqMatchTypeKeywordMatchAny.String(), conf.FaqMatchTypeEmbeddingSimilarity.String(), conf.FaqMatchTypeFullMatch.String()),
			conf.EmbeddingModelName:           "bge-embedding-ai-zhida-online",
		},
		stream_chat_default_tab_conf.FaqMLogic: {
			conf.ConfigFaqSimilarityThreshold: "faq.embeddingSimilarityThreshold",
			conf.ConfigFaqKey:                 string(conf.SearchTabFAQ),
			conf.ConfigFaqMatchTypeKey:        conf.BuildConfigArrayValue(conf.FaqMatchTypeFullMatch.String(), conf.FaqMatchTypeKeywordMatchAll.String(), conf.FaqMatchTypeKeywordMatchAny.String(), conf.FaqMatchTypeEmbeddingSimilarity.String()),
			conf.EmbeddingModelName:           "bge-embedding-ai-zhida-online",
		},
		stream_chat_default_tab_conf.QueryMergeLogic: {
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
					conf.NewChatMsgConfigByChatHistoryAndLimit(stream_chat_default_tab_conf.ChatHistoryNewLimit, 8*1024),
					conf.NewChatMsgConfigByCustomQuery("1309", ""),
				},
			}.ToJsonString(),
		},
	}

	// 获取TrafficSource 自定义配置
	customConfigMap := c.GetTrafficCustomConfig(requestCtx, user)
	// 覆盖更新config
	logicConfigMap = stage_handler.OverrideGraphStageConfig(logicConfigMap, customConfigMap)
	return logicConfigMap
}

// GetTrafficCustomConfig 获取流量自定义配置
func (c *StageInitConfig) GetTrafficCustomConfig(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// 注：只参与 recall 之前的配置
	switch requestCtx.GetBizContext().GetTrafficSource() {
	// 直答、直答专业版、有数
	case proto.TrafficSource_undefined_traffic, proto.TrafficSource_zhida, proto.TrafficSource_zhida_knowledge_ground, proto.TrafficSource_zhida_pro,
		proto.TrafficSource_commercial_data_insight:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.QueryRouterLogic: {
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
						},
						DefaultChoice: macro.GetQueryRouteSearch(),
					},
				),
			},
		}
		return customConfig
	// 直答 gr
	case proto.TrafficSource_zhida_gr_demo:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.QueryRouterLogic: {
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
							macro.GetQueryRouteAuthor(),
							macro.GetQueryRouteSearch(),
						},
						DefaultChoice: macro.GetQueryRouteSearch(),
					},
				),
			},
			stream_chat_default_tab_conf.FaqLogic: {
				conf.ConfigFaqKey: string(conf.ZhihaituFAQ),
			},
			stream_chat_default_tab_conf.FaqMLogic: {
				conf.ConfigFaqKey: string(conf.ZhihaituFAQ),
			},
		}
		return customConfig
	// 实体词
	case proto.TrafficSource_entity, proto.TrafficSource_entity_preview, proto.TrafficSource_comment_entity, proto.TrafficSource_search_entity_preview:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.QueryDefinitionLogic: {
				conf.IsEnableLogic: "true",
			},
			stream_chat_default_tab_conf.ChatHistoryLogic: {
				conf.ChatHistorySkip.ToConvert(): "true",
			},
			stream_chat_default_tab_conf.QueryRouterLogic: {
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
			},
			stream_chat_default_tab_conf.QueryMergeLogic: {
				conf.QueryMergeSkipAndSetAsQuery: "true",
			},
		}
		return customConfig
	// 直答-AI摘要
	case proto.TrafficSource_zhida_summary:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.QueryDefinitionLogic: {
				conf.IsEnableLogic: "true",
			},
			stream_chat_default_tab_conf.ChatHistoryLogic: {
				conf.ChatHistorySkip.ToConvert(): "true",
			},
			stream_chat_default_tab_conf.QueryRouterLogic: {
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
			},
			stream_chat_default_tab_conf.QueryMergeLogic: {
				conf.QueryMergeSkipAndSetAsQuery: "true",
			},
		}
		return customConfig
	// 综搜首卡 & AI 搜索卡
	case proto.TrafficSource_ai_search_card, proto.TrafficSource_ai_search_card_preview,
		proto.TrafficSource_ai_search_card_full_search, proto.TrafficSource_ai_search_card_full_search_preview,
		proto.TrafficSource_ai_search_general:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.QueryRouterLogic: {
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
			},
			stream_chat_default_tab_conf.ChatHistoryLogic: {
				conf.ChatHistorySkip.ToConvert(): "true",
			},
			stream_chat_default_tab_conf.QueryMergeLogic: {
				conf.QueryMergeSkipAndSetAsQuery: "true",
			},
		}
		return customConfig
	// 回答详情页出相关追问，点击跳转直答
	case proto.TrafficSource_below_banner_question:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.QueryRouterLogic: {
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
			},
			stream_chat_default_tab_conf.ChatHistoryLogic: {
				conf.ChatHistorySkip.ToConvert(): "true",
			},
			stream_chat_default_tab_conf.QueryMergeLogic: {
				conf.QueryMergeSkipAndSetAsQuery: "true",
			},
			stream_chat_default_tab_conf.QuKeywordFetcherLogic: {
				conf.BaseConfigSkip: "true",
			},
		}
		return customConfig
	// AI 垂搜（新策略只APP生效）
	case proto.TrafficSource_search_tab:
		switch requestCtx.GetBizContext().GetClientSource() {
		case proto.ClientSource_ZHIHU_APP:
			customConfig := map[string]map[string]string{
				stream_chat_default_tab_conf.QueryRouterLogic: {
					conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
				},
				stream_chat_default_tab_conf.ChatHistoryLogic: {
					conf.ChatHistorySkip.ToConvert(): "true",
				},
				stream_chat_default_tab_conf.QueryMergeLogic: {
					conf.QueryMergeSkipAndSetAsQuery: "true",
				},
				stream_chat_default_tab_conf.QuKeywordFetcherLogic: {
					conf.BaseConfigSkip: "true",
				},
			}
			return customConfig
		default:
			customConfig := map[string]map[string]string{
				stream_chat_default_tab_conf.QueryRouterLogic: {
					conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
				},
				stream_chat_default_tab_conf.ChatHistoryLogic: {
					conf.ChatHistorySkip.ToConvert(): "true",
				},
				stream_chat_default_tab_conf.QueryMergeLogic: {
					conf.QueryMergeSkipAndSetAsQuery: "true",
				},
			}
			return customConfig
		}
	// 其他
	default:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.QueryRouterLogic: {
				conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.RouteConfig{IsEnable: false}),
			},
			stream_chat_default_tab_conf.ChatHistoryLogic: {
				conf.ChatHistorySkip.ToConvert(): "true",
			},
			stream_chat_default_tab_conf.QueryMergeLogic: {
				conf.QueryMergeSkipAndSetAsQuery: "true",
			},
		}
		return customConfig
	}
}
