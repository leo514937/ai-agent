package conf_stage

import (
	"context"
	"encoding/json"
	"strings"

	apollo "git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/conf_stage/operation_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources/ab"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	mapset "github.com/deckarep/golang-set"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type StageGenerateConfig struct {
	stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
	operationParser *operation_config.CachedParser
}

func (c *StageGenerateConfig) GetConfigMap(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		// 安全审核 answer 与 word
		stream_chat_default_tab_conf.RelevantQuerySecurityReviewLogic: {conf.RiskConfigWordSource.ToConvert(): proto.QueryType_RELATE_WORD_QUESTION.String()},
		stream_chat_default_tab_conf.SecurityReviewOutLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:         rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:            proto.ChatType_ZHIDA_TAB.String(),
				ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
			}.ToJsonString(),
		},
		// 存储query 缓存
		stream_chat_default_tab_conf.SaveQueryResultLogic: {
			// 默认只开启预制词缓存
			conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
		},
	}

	// 获取TrafficSource 自定义配置
	customConfigMap := c.GetTrafficCustomConfig(ctx, requestCtx, user)
	customConfigMap = c.ChangeConfigByAb(ctx, requestCtx, customConfigMap)
	// 如果接口指定了 model 参数则覆盖
	if requestCtx.GetBizContext().GetChatExtraInfo() != nil && requestCtx.GetBizContext().GetChatExtraInfo().GetModelArgs() != nil {
		modelArgs := requestCtx.GetBizContext().GetChatExtraInfo().GetModelArgs()
		// 获取chat配置，并修改一些 可修改的参数
		chatConfigStr := customConfigMap[stream_chat_default_tab_conf.StreamChatLogic][conf.JsonConfigLogicKey.ToConvert()]
		chatConfig := conf.ChatConfig{}
		msgConfigErr := json.Unmarshal([]byte(chatConfigStr), &chatConfig)
		if msgConfigErr == nil {
			if modelArgs.GetMaxTokens() != nil {
				chatConfig.MaxTokens = lo.ToPtr[int32](modelArgs.GetMaxTokens().GetValue())
			}
			if modelArgs.GetTemperature() != nil {
				chatConfig.Temperature = lo.ToPtr[float32](modelArgs.GetTemperature().GetValue())
			}
			if modelArgs.GetTopK() != nil {
				chatConfig.TopK = lo.ToPtr[int32](modelArgs.GetTopK().GetValue())
			}
			if modelArgs.GetTopP() != nil {
				chatConfig.TopP = lo.ToPtr[float32](modelArgs.GetTopP().GetValue())
			}
			if modelArgs.GetPresencePenalty() != nil {
				chatConfig.PresencePenalty = lo.ToPtr[float32](modelArgs.GetPresencePenalty().GetValue())
			}
			if modelArgs.GetRepetitionPenalty() != nil {
				chatConfig.RepetitionPenalty = lo.ToPtr[float32](modelArgs.GetRepetitionPenalty().GetValue())
			}
			if len(modelArgs.GetStop()) > 0 {
				chatConfig.Stop = modelArgs.GetStop()
			}
			customConfigMap[stream_chat_default_tab_conf.StreamChatLogic][conf.JsonConfigLogicKey.ToConvert()] = chatConfig.ToJsonString()
		}
	}

	// 覆盖更新config
	logicConfigMap = stage_handler.OverrideGraphStageConfig(logicConfigMap, customConfigMap)
	return logicConfigMap
}

// GetMainCustomConfig 获得主配置
func (c *StageGenerateConfig) GetMainCustomConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], isForceDisableReferencesCmd bool) map[string]map[string]string {
	query := requestCtx.GetBizContext().RequestMessage().GetText()
	// 如果是 zhida v2 版本则开启思考分离
	isV2 := requestCtx.GetBizContext().RequestHeader().Version == graph_constant.ZhiDaV2Version
	// 是否开启思考模式
	isThink := lo.Ternary(requestCtx.GetBizContext().GetCustomChatModel() != proto.ChatModel_CM_ZHI_HAI_TU, "true", "false")
	// 思考模式下 是否分离think
	isThinkSeparated := lo.Ternary(isV2, "true", "false")
	// 是否知乎彩蛋 == 开启彩蛋 && 以如何评价/如何看待开头 && 没有挂载内容
	isZhihuEasterEgg := apollo.GetBool(macro.UseEasterEgg, false) && (strings.HasPrefix(query, "如何评价") || strings.HasPrefix(query, "如何看待")) && requestCtx.GetBizContext().GetCurrReferenceMount().GetMountLength() == 0
	// 是否禁止角标
	isDisableReferences := "true"
	if !isForceDisableReferencesCmd {
		isDisableReferences = lo.Ternary(isZhihuEasterEgg, "true", "false")
	}

	// 系统promptId
	systemPromptId := lo.Ternary(isZhihuEasterEgg, "zhida_v2_reasoning_easter_egg_system", "zhida_v2_reasoning_system")

	// 获取操作配置(目前只在主场景支持该功能)
	operationJsonConfigStr := impl.DefaultAiIngressRPCImpl.GetOperationConfig(ctx, requestCtx.GetBizContext().GetChatExtraInfo().GetOperationId())
	opBaseConf, opBaseConfErr := c.operationParser.ParseMessage(operationJsonConfigStr)
	var opPromptConf *operation_config.PromptMessage
	if opBaseConfErr == nil {
		switch opBaseConf.GetType() {
		case operation_config.MessageTypePrompt:
			{
				if promptMsg, ok := opBaseConf.(*operation_config.PromptMessage); ok {
					opPromptConf = promptMsg
				}
			}
		default:
		}
	}

	// 模型基础配置
	chatBaseConfig := getZhidaV2ModelByConfig(requestCtx, false, opPromptConf)

	// 模型Msg配置
	var chatMsgConfig string

	// 纯文档独立msg
	if isV2 && requestCtx.GetBizContext().IsMountPureDoc() {
		var realSystemPromptId = systemPromptId
		if opPromptConf != nil && opPromptConf.SystemPrompt != "" {
			realSystemPromptId = opPromptConf.SystemPrompt
		}

		var realUserPromptId = "zhida_v2_pure_docs_user"
		if opPromptConf != nil && opPromptConf.UserPromptPureDocsPrompt != "" {
			realUserPromptId = opPromptConf.UserPromptPureDocsPrompt
		}

		chatMsgConfig = conf.MsgConfig{
			SystemPromptId: realSystemPromptId,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryLimit10),
				conf.NewChatMsgConfigByKnowledge(realUserPromptId, "", ""),
			},
		}.ToJsonString()
	} else {
		var realSystemPromptId = systemPromptId
		if opPromptConf != nil && opPromptConf.SystemPrompt != "" {
			realSystemPromptId = opPromptConf.SystemPrompt
		}

		var realUserPromptId = "zhida_v2_reasoning_user_citation"
		if opPromptConf != nil && opPromptConf.UserPromptCitationPrompt != "" {
			realUserPromptId = opPromptConf.UserPromptCitationPrompt
		}

		chatMsgConfig = conf.MsgConfig{
			SystemPromptId: realSystemPromptId,
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryLimit10),
				conf.NewChatMsgConfigByKnowledge(realUserPromptId, "", ""),
			},
		}.ToJsonString()
	}

	return map[string]map[string]string{
		stream_chat_default_tab_conf.StreamChatLogic: {
			conf.StreamChatDisableReferences:    isDisableReferences,
			conf.JsonConfigLogicKey.ToConvert(): chatBaseConfig,
			conf.ChatMessageJsonConfig:          chatMsgConfig,
			conf.StreamChatIsThinkSeparated:     isThinkSeparated,
			conf.StreamChatIsUseThink:           isThink,
		},
		stream_chat_default_tab_conf.ChatLogic: defChatLogicConfig,
	}
}

// GetTrafficCustomConfig 获取流量自定义配置
func (c *StageGenerateConfig) GetTrafficCustomConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// wru 检测
	wruConfig := c.GetWRUConfig(ctx, requestCtx, user)
	if len(wruConfig) > 0 {
		return wruConfig
	}

	// 答主搜索&搜自己专属
	authorConfig := c.GetAuthorConfig(ctx, requestCtx, user)
	if len(authorConfig) > 0 {
		return authorConfig
	}

	switch requestCtx.GetBizContext().GetTrafficSource() {
	// 直答、直答专业版、内部QA助手、有数、AI垂直搜索
	case proto.TrafficSource_undefined_traffic, proto.TrafficSource_zhida, proto.TrafficSource_zhida_knowledge_ground, proto.TrafficSource_zhida_pro,
		proto.TrafficSource_internal_qa:
		return c.GetMainCustomConfig(ctx, requestCtx, user, false)
	case proto.TrafficSource_commercial_data_insight:
		return c.GetMainCustomConfig(ctx, requestCtx, user, true)
	// 直答 gr
	case proto.TrafficSource_zhida_gr_demo:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["zhida-doubao-seed-1-6-flash"].ToJsonString(),
				conf.StreamChatDisableReferences:    "true",
				conf.ChatMessageJsonConfig: conf.MsgConfig{
					IsCustom:        true,
					SystemPromptId:  "zhida_summary_system_concise",
					SystemPromptTag: "gov_rel",
					// config 顺序 决定 msg 的拼接顺序
					MsgConfigArr: []conf.ChatMsgConfig{
						conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v2", "", ""),
						conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
						conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryNewLimit),
						conf.NewChatMsgConfigByQuery(),
					},
				}.ToJsonString(),
			},
			stream_chat_default_tab_conf.ChatLogic: {
				conf.ChatDisable: "true",
			},
		}
		return customConfig
	// 直答-AI摘要
	case proto.TrafficSource_zhida_summary:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.StreamChatDisableReferences:    "true",
				conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["virtual-llm-ai-summary-online"].ToJsonString(),
				conf.ChatMessageJsonConfig: conf.MsgConfig{
					SystemPromptId: "1304",
					// config 顺序 决定 msg 的拼接顺序
					MsgConfigArr: []conf.ChatMsgConfig{
						conf.NewChatMsgConfigByKnowledge("zhida_v2_doc_summary_content", "", ""),
						conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
						conf.NewChatMsgConfigByCustomQuery("zhida_v2_doc_summary_user", ""),
					},
				}.ToJsonString(),
			},
			stream_chat_default_tab_conf.ChatLogic: defChatLogicConfig,
		}
		return customConfig
	// 实体词 preview。包括：实体词半弹层和实体词跳综搜首卡
	case proto.TrafficSource_entity_preview, proto.TrafficSource_search_entity_preview:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.StreamChatDisableReferences:    "true",
				conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["virtual-llm-entityword-online"].ToJsonString(),
				conf.ChatMessageJsonConfig:          defSimpleStreamChatLogicMsgConfig,
			},
			stream_chat_default_tab_conf.ChatLogic: {
				conf.ChatDisable: "true",
			},
		}
		if requestCtx.GetBizContext().GetABContext(macro.ZlabSceneIdAiRecDomain).GetZlabAB(ab.EntityFlashModelExp2) {
			customConfig[stream_chat_default_tab_conf.StreamChatLogic] = map[string]string{
				conf.StreamChatDisableReferences:    "true",
				conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["doubao-seed-16-flash-entityword"].ToJsonString(),
				conf.ChatMessageJsonConfig:          defSimpleStreamChatLogicMsgConfig,
			}
		}
		return customConfig
	// 实体词 - 深入
	case proto.TrafficSource_entity, proto.TrafficSource_comment_entity:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["virtual-llm-entityword-online"].ToJsonString(),
				conf.ChatMessageJsonConfig:          defStreamChatLogicMsgConfig,
			},
			stream_chat_default_tab_conf.ChatLogic: defChatLogicConfig,
		}
		if requestCtx.GetBizContext().GetABContext(macro.ZlabSceneIdAiRecDomain).GetZlabAB(ab.EntityFlashModelExp2) {
			customConfig[stream_chat_default_tab_conf.StreamChatLogic] = map[string]string{
				conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["doubao-seed-16-flash-entityword"].ToJsonString(),
				conf.ChatMessageJsonConfig:          defSimpleStreamChatLogicMsgConfig,
			}
		}
		return customConfig
	// 翻译
	case proto.TrafficSource_zhida_translation:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["zh-llm-14b-online"].ToJsonString(),
				conf.ChatMessageJsonConfig: conf.MsgConfig{
					IsCustom:                    true,
					SystemDefaultPromptTemplate: "you are a helpful assistant.",
					MsgConfigArr: []conf.ChatMsgConfig{
						conf.NewChatMsgConfigByKnowledge("zhida_v2_reasoning_translate_user", "", ""),
					},
				}.ToJsonString(),
			},
			stream_chat_default_tab_conf.ChatLogic: {
				conf.ChatDisable: "true",
			},
		}
		return customConfig
	// 综搜首卡 preview
	case proto.TrafficSource_ai_search_card_preview, proto.TrafficSource_ai_search_card_full_search_preview:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.StreamChatDisableReferences:    "true",
				conf.JsonConfigLogicKey.ToConvert(): getZhidaV2Model(requestCtx, true),
				conf.ChatMessageJsonConfig: conf.MsgConfig{
					IsCustom:       true,
					SystemPromptId: "ai_search_card_system_v2",
					// config 顺序 决定 msg 的拼接顺序
					MsgConfigArr: []conf.ChatMsgConfig{
						conf.NewChatMsgConfigByKnowledge("ai_search_card_knowledge", "", ""),
						conf.NewChatMsgConfigByAssistantResponse("好的，我已理解参考内容。我会按照系统指令要求来回答你的问题!"),
						conf.NewChatMsgConfigByCustomQuery("ai_search_card_query", ""),
					},
				}.ToJsonString(),
			},
			stream_chat_default_tab_conf.ChatLogic: {
				conf.ChatDisable: "true",
			},
		}
		return customConfig
	// ai 搜-通用
	case proto.TrafficSource_ai_search_general:
		// 开启亲自答角标
		modelConfig := getZhidaV2Model(requestCtx, true)
		chatConfig := conf.ChatConfig{}
		msgConfigErr := json.Unmarshal([]byte(modelConfig), &chatConfig)

		if msgConfigErr == nil && chatConfig.IsCiteV2 {
			chatConfig.IsInPersonCiteV2 = true
			chatConfig.Temperature = lo.ToPtr[float32](1.0)
			modelConfig = chatConfig.ToJsonString()
		}

		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.JsonConfigLogicKey.ToConvert(): modelConfig,
				conf.ChatMessageJsonConfig: conf.MsgConfig{
					IsCustom:       true,
					SystemPromptId: "ai_search_card_system_general",
					// config 顺序 决定 msg 的拼接顺序
					MsgConfigArr: []conf.ChatMsgConfig{
						conf.NewChatMsgConfigByKnowledge("ai_search_card_knowledge_general", "", ""),
						conf.NewChatMsgConfigByAssistantResponse("好的，我已理解参考内容。我会按照系统指令要求来回答你的问题!"),
						conf.NewChatMsgConfigByCustomQuery("ai_search_card_query", ""),
					},
				}.ToJsonString(),
			},
			stream_chat_default_tab_conf.ChatLogic: defChatLogicConfig,
		}
		return customConfig
	// 综搜首卡 - 深入
	case proto.TrafficSource_ai_search_card, proto.TrafficSource_ai_search_card_full_search:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.JsonConfigLogicKey.ToConvert(): getZhidaV2Model(requestCtx, true),
				conf.ChatMessageJsonConfig: conf.MsgConfig{
					SystemPromptId: "ai_search_card_system_v2",
					// config 顺序 决定 msg 的拼接顺序
					MsgConfigArr: []conf.ChatMsgConfig{
						conf.NewChatMsgConfigByKnowledge("ai_search_card_knowledge", "", ""),
						conf.NewChatMsgConfigByAssistantResponse("好的，我已理解参考内容。我会按照系统指令要求来回答你的问题!"),
						conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryNewLimit),
						conf.NewChatMsgConfigByQueryOrQueryDefinition("query_definition", "", ""),
					},
				}.ToJsonString(),
			},
			stream_chat_default_tab_conf.ChatLogic: defChatLogicConfig,
		}
		return customConfig
	// 默认简洁回答模式，且出相关词
	case proto.TrafficSource_underlined_word, proto.TrafficSource_ai_search_query, proto.TrafficSource_suggestion,
		proto.TrafficSource_below_banner_question, proto.TrafficSource_right_banner_question, proto.TrafficSource_ai_summary_under_answer,
		proto.TrafficSource_unsatisfied_search, proto.TrafficSource_follow_query, proto.TrafficSource_viewpoint_page,
		proto.TrafficSource_question_edit_page, proto.TrafficSource_search_tab_preview, proto.TrafficSource_noanswer_search:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.StreamChatDisableReferences:    "true",
				conf.JsonConfigLogicKey.ToConvert(): getZhidaV2Model(requestCtx, true),
				conf.ChatMessageJsonConfig:          defSimpleStreamChatLogicMsgConfig,
			},
			stream_chat_default_tab_conf.ChatLogic: defChatLogicConfig,
		}
		return customConfig
	// AI 垂搜（新策略只APP生效）
	case proto.TrafficSource_search_tab:
		switch requestCtx.GetBizContext().GetClientSource() {
		case proto.ClientSource_ZHIHU_APP:
			return c.GetMainCustomConfig(ctx, requestCtx, user, false)
		default:
			customConfig := map[string]map[string]string{
				stream_chat_default_tab_conf.StreamChatLogic: {
					conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["virtual-llm-searchcard-online"].ToJsonString(),
					conf.ChatMessageJsonConfig:          defStreamChatLogicMsgConfig,
				},
				stream_chat_default_tab_conf.ChatLogic: defChatLogicConfig,
			}
			return customConfig
		}
	// 其他 默认关闭输出相关词
	default:
		customConfig := map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.StreamChatDisableReferences:    "true",
				conf.JsonConfigLogicKey.ToConvert(): getZhidaV2Model(requestCtx, true),
				conf.ChatMessageJsonConfig:          defSimpleStreamChatLogicMsgConfig,
			},
			stream_chat_default_tab_conf.ChatLogic: {
				conf.ChatDisable: "true",
			},
		}
		return customConfig
	}
}

var aiSearchCardTrafficSourceSet = mapset.NewSet(
	proto.TrafficSource_ai_search_card_preview,
	proto.TrafficSource_ai_search_card,
	proto.TrafficSource_ai_search_card_full_search_preview,
	proto.TrafficSource_ai_search_card_full_search,
)

func (c *StageGenerateConfig) ChangeConfigByAb(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], customConfigMap map[string]map[string]string) map[string]map[string]string {
	if requestCtx.GetBizContext().GetABContext(macro.ZlabSceneIdAiRecDomain).GetZlabAB(ab.EntitySearchModelExp1) {
		streamChatConfig := customConfigMap[stream_chat_default_tab_conf.StreamChatLogic]
		if streamChatConfig == nil {
			return customConfigMap
		}
		if requestCtx.GetBizContext().GetTrafficSource() == proto.TrafficSource_ai_search_card_preview || requestCtx.GetBizContext().GetTrafficSource() == proto.TrafficSource_ai_search_card_full_search_preview {
			// 同步修改 ChatMessageJsonConfig
			streamChatConfig[conf.ChatMessageJsonConfig] = conf.MsgConfig{
				IsCustom:       true,
				SystemPromptId: "ai_search_card_system_v2",
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v3", "", ""),
					conf.NewChatMsgConfigByAssistantResponse("好的，我已理解参考内容。我会按照系统指令要求来回答你的问题!"),
					conf.NewChatMsgConfigByCustomQuery("ai_search_card_query", ""),
				},
			}.ToJsonString()
		}
	}

	return customConfigMap
}

// GetWRUConfig 获得WRU配置
func (c *StageGenerateConfig) GetWRUConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// 获取意图
	intention, _ := requestCtx.DataMap().GetString(ctx, graph_macro.ZagKeyIntention)
	currIntentionType := macro.IntentionType(intention)

	// 意图=WRU 没有任何召回
	if currIntentionType == macro.GetQueryRouteIdentity() {
		switch requestCtx.GetBizContext().GetTrafficSource() {
		case proto.TrafficSource_zhida_gr_demo:
			// gr wru
			return map[string]map[string]string{
				stream_chat_default_tab_conf.StreamChatLogic: {
					conf.StreamChatDisableReferences:    "true",
					conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["zhida-doubao-seed-1-6-flash"].ToJsonString(),
					conf.ChatMessageJsonConfig: conf.MsgConfig{
						SystemPromptId:  "zhida_whoareyou_summary_system",
						SystemPromptTag: "gov_rel",
						// config 顺序 决定 msg 的拼接顺序
						MsgConfigArr: []conf.ChatMsgConfig{
							conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryNewLimit),
							conf.NewChatMsgConfigByKnowledge("zhida_whoareyou_summary_user", "", "gov_rel"),
						},
					}.ToJsonString(),
				},
				stream_chat_default_tab_conf.ChatLogic: {
					conf.ChatDisable: "true",
				},
			}
		default:
			// 如果是 zhida v2 版本则开启思考分离
			isV2 := requestCtx.GetBizContext().RequestHeader().Version == graph_constant.ZhiDaV2Version
			// 是否开启思考模式
			isThink := lo.Ternary(requestCtx.GetBizContext().GetCustomChatModel() != proto.ChatModel_CM_ZHI_HAI_TU, "true", "false")
			// 思考模式下 是否分离think
			isThinkSeparated := lo.Ternary(isV2, "true", "false")
			return map[string]map[string]string{
				stream_chat_default_tab_conf.StreamChatLogic: {
					conf.StreamChatDisableReferences:    "true",
					conf.StreamChatIsThinkSeparated:     isThinkSeparated,
					conf.StreamChatIsUseThink:           isThink,
					conf.JsonConfigLogicKey.ToConvert(): getZhidaV2Model(requestCtx, false),
					conf.ChatMessageJsonConfig: conf.MsgConfig{
						SystemPromptId: "zhida_v2_wru_system",
						// config 顺序 决定 msg 的拼接顺序
						MsgConfigArr: []conf.ChatMsgConfig{
							conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryNewLimit),
							conf.NewChatMsgConfigByQuery(),
						},
					}.ToJsonString(),
				},
				stream_chat_default_tab_conf.ChatLogic: {
					conf.ChatDisable: "true",
				},
			}
		}
	}
	return map[string]map[string]string{}
}

// GetAuthorConfig 获得搜答主配置
func (c *StageGenerateConfig) GetAuthorConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// 获取意图 判断为搜答主场景
	intention, _ := requestCtx.DataMap().GetString(ctx, graph_macro.ZagKeyIntention)
	currIntentionType := macro.IntentionType(intention)
	isSearchAuthorOther := len(requestCtx.GetBizContext().GetKnowledgeBases()) == 1 &&
		currIntentionType == macro.GetQueryRouteAuthor() &&
		requestCtx.GetBizContext().GetKnowledgeBases()[0] == proto.KnowledgeBaseType_KBT_ZHIHU

	isSearchAuthorSelf := false
	// 召回结果 如果为空 有专属的为空配置( 如果 isExist 为 false 则表示 还为走到召回阶段)
	if recallStageRes, isExist := c.GetRecallStageRes(requestCtx); isExist && len(recallStageRes) == 0 {
		isSearchAuthorSelf = len(lo.Filter(recallStageRes, func(item *data_frame.ItemData[entities.Item], index int) bool {
			return item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ContainSource(conf.KbSourceAuthorSelf)
		})) > 0
	}

	if isSearchAuthorOther || isSearchAuthorSelf {
		return map[string]map[string]string{
			stream_chat_default_tab_conf.StreamChatLogic: {
				conf.StreamChatDisableReferences:    "true",
				conf.JsonConfigLogicKey.ToConvert(): getZhidaV2Model(requestCtx, true),
				conf.ChatMessageJsonConfig:          defStreamChatLogicMsgConfig,
			},
			stream_chat_default_tab_conf.ChatLogic: {
				conf.ChatDisable: "true",
			},
		}
	}
	return map[string]map[string]string{}
}

// GetRecallStageRes 获得ReRank阶段结果
func (c *StageGenerateConfig) GetRecallStageRes(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) ([]*data_frame.ItemData[entities.Item], bool) {
	// 召回结果(只获取判断为used 结果)
	recallItems, isExist := requestCtx.GetCommonContext().GetLogicData(conf.RecallCardLogicStoreKey.String()).([]*data_frame.ItemData[entities.Item])
	if isExist {
		recallItems = lo.Filter(recallItems, func(item *data_frame.ItemData[entities.Item], index int) bool {
			return item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used
		})
	}
	return recallItems, isExist
}

func getZhidaV2Model(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], isOnlyDef bool) string {
	return getZhidaV2ModelByConfig(requestCtx, isOnlyDef, nil)
}

func getZhidaV2ModelByConfig(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], isOnlyDef bool, conf *operation_config.PromptMessage) string {
	// 如果是 zhida v2 版本则开启思考分离
	isCiteV2 := requestCtx.GetBizContext().RequestHeader().Version == graph_constant.ZhiDaV2Version
	modelName := "ds-v3_1-zhida-online"

	// ai 垂搜需要单独更换模型
	if requestCtx.GetBizContext().RequestHeader().GetTrafficSource() == proto.TrafficSource_search_tab {
		modelName = "zhi-qwen3-14b-4090"
	}

	// 模型基础配置
	if !isOnlyDef && requestCtx.GetBizContext().GetCustomChatModel() != proto.ChatModel_CM_ZHI_HAI_TU {
		modelName = "ds-v3_1-think-zhida-online"
	}

	// 综搜直答卡片使用 doubao-seed-16-aisearch 模型
	if aiSearchCardTrafficSourceSet.Contains(requestCtx.GetBizContext().GetTrafficSource()) {
		modelName = "doubao-seed-16-aisearch"
	}

	// ai 搜使用 doubao-seed-16-aisearch 模型
	if requestCtx.GetBizContext().GetTrafficSource() == proto.TrafficSource_ai_search_general {
		modelName = "doubao-seed-16-aisearch"
	}

	// 设置操作配置
	if conf != nil {
		modelNameTmp := lo.Ternary(conf.ModelName != "", conf.ModelName, modelName)
		if _, isExist := modelConfigDict[modelNameTmp]; isExist {
			modelName = modelNameTmp
		}
	}

	modelConfig := modelConfigDict[modelName]
	modelConfig.IsCiteV2 = isCiteV2
	return modelConfig.ToJsonString()
}

var defStreamChatLogicMsgConfig = conf.MsgConfig{
	SystemPromptId: "zhida_summary_system_elaborated",
	// config 顺序 决定 msg 的拼接顺序
	MsgConfigArr: []conf.ChatMsgConfig{
		conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v2", "", ""),
		conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
		conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryNewLimit),
		conf.NewChatMsgConfigByQueryOrQueryDefinition("query_definition", "", ""),
	},
}.ToJsonString()

var defSimpleStreamChatLogicMsgConfig = conf.MsgConfig{
	SystemPromptId: "zhida_summary_system_concise",
	// config 顺序 决定 msg 的拼接顺序
	MsgConfigArr: []conf.ChatMsgConfig{
		conf.NewChatMsgConfigByKnowledge("zhida_summary_user_v2", "", ""),
		conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
		conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryNewLimit),
		conf.NewChatMsgConfigByQueryOrQueryDefinition("query_definition", "", ""),
	},
}.ToJsonString()

var defChatLogicConfig = map[string]string{
	conf.JsonConfigLogicKey.ToConvert(): modelConfigDict["question-gen-14b"].ToJsonString(),
	conf.ChatMessageJsonConfig: conf.MsgConfig{
		SystemPromptId: "1304",
		// config 顺序 决定 msg 的拼接顺序
		MsgConfigArr: []conf.ChatMsgConfig{
			conf.NewChatMsgConfigByKnowledge("related_question_v3_user", "", ""),
		},
	}.ToJsonString(),
}

var modelConfigDict = map[string]conf.ChatConfig{
	"question-gen-14b": {
		ModelName:     "question-gen-14b",
		ContextLength: 8 * 1024,
		MaxTokens:     lo.ToPtr[int32](128),
		Stop: []string{
			"<|im_end|>",
			"<|endoftext|>",
		},
		TopP:             lo.ToPtr[float32](0.8),
		Temperature:      lo.ToPtr[float32](0.5),
		PresencePenalty:  lo.ToPtr[float32](0.5),
		FrequencyPenalty: lo.ToPtr[float32](0.0),
		Stage:            proto.BusinessStage_RELEVANT_QUERY,
	},
	"zhi-qwen3-14b-4090": {
		ModelName:     "zhi-qwen3-14b-4090",
		MaxTokens:     lo.ToPtr[int32](8 * 1024),
		ContextLength: 24 * 1024,
		Stop: []string{
			"<think>",
		},
		EnableThinking:    lo.ToPtr[bool](false),
		RepetitionPenalty: lo.ToPtr[float32](1.1),
		Stage:             proto.BusinessStage_GENERATION,
		SecurityConfig: &conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
	"zhida-doubao-seed-1-6-flash": {
		ModelName:          "zhida-doubao-seed-1-6-flash",
		IsReferences:       true,
		CiteMaxCount:       5,
		ContextLength:      64 * 1024,
		ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
		MaxTokens:          lo.ToPtr[int32](8 * 1024),
		TopP:               lo.ToPtr[float32](0.8),
		Stage:              proto.BusinessStage_GENERATION,
		ThinkingType:       conf.ThinkingTypeDisabled,
		SecurityConfig: &conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
	"ds-v3_1-think-zhida-online": {
		ModelName:          "ds-v3_1-think-zhida-online",
		IsReferences:       true,
		CiteMaxCount:       5,
		ContextLength:      64 * 1024,
		ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
		MaxTokens:          lo.ToPtr[int32](16 * 1024),
		TopP:               lo.ToPtr[float32](0.8),
		Stage:              proto.BusinessStage_GENERATION,
		SecurityConfig: &conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
	"ds-v3_1-zhida-online": {
		ModelName:          "ds-v3_1-zhida-online",
		IsReferences:       true,
		CiteMaxCount:       5,
		ContextLength:      64 * 1024,
		ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
		MaxTokens:          lo.ToPtr[int32](16 * 1024),
		TopP:               lo.ToPtr[float32](0.8),
		Stage:              proto.BusinessStage_GENERATION,
		SecurityConfig: &conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
	"ds-v3-zhida-online": {
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
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
	"ds-r1-full-awq-online": {
		ModelName:          "ds-r1-full-awq-online",
		IsReferences:       true,
		IsCiteV2:           false,
		ContextLength:      54 * 1024,
		ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
		MaxTokens:          lo.ToPtr[int32](8 * 1024),
		TopP:               lo.ToPtr[float32](0.8),
		Stage:              proto.BusinessStage_GENERATION,
		SecurityConfig: &conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
	"virtual-llm-ai-summary-online": {
		ModelName:     "virtual-llm-ai-summary-online",
		ContextLength: 8 * 1024,
		IsReferences:  true,
		CiteMaxCount:  5,
		MaxTokens:     lo.ToPtr[int32](500),
		Stop: []string{
			"</s>", "<|im_end|>",
		},
		Temperature:       lo.ToPtr[float32](0.2),
		TopP:              lo.ToPtr[float32](0.9),
		TopK:              lo.ToPtr[int32](50),
		RepetitionPenalty: lo.ToPtr[float32](1.1),
		PresencePenalty:   nil,
		FrequencyPenalty:  nil,
		Stage:             proto.BusinessStage_GENERATION,
		SecurityConfig: &conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
	"virtual-llm-searchcard-online": {
		ModelName:     "virtual-llm-searchcard-online",
		ContextLength: 16 * 1024,
		IsReferences:  true,
		CiteMaxCount:  5,
		MaxTokens:     lo.ToPtr[int32](2048),
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
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
	"doubao-seed-16-aisearch": {
		ModelName:         "doubao-seed-16-aisearch",
		ContextLength:     28 * 1024,
		IsReferences:      true,
		CiteMaxCount:      5,
		MaxTokens:         lo.ToPtr[int32](4096),
		Stop:              []string{},
		ThinkingType:      conf.ThinkingTypeDisabled,
		Temperature:       lo.ToPtr[float32](0.8),
		TopP:              lo.ToPtr[float32](0.8),
		TopK:              nil,
		RepetitionPenalty: nil,
		PresencePenalty:   nil,
		FrequencyPenalty:  nil,
		Stage:             proto.BusinessStage_GENERATION,
		SecurityConfig: &conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
		ExtraBody: map[string]interface{}{
			"thinking": map[string]string{"type": "disabled"},
		},
		UseSystemPromptPrefixCache: true,
		ModelApi:                   conf.ModelApiResponses,
	},
	"doubao-seed-16-flash-entityword": {
		ModelName:         "doubao-seed-16-flash-entityword",
		ContextLength:     16 * 1024,
		IsReferences:      true,
		CiteMaxCount:      5,
		MaxTokens:         lo.ToPtr[int32](4096),
		Stop:              []string{},
		ThinkingType:      conf.ThinkingTypeDisabled,
		Temperature:       lo.ToPtr[float32](0.8),
		TopP:              lo.ToPtr[float32](0.8),
		TopK:              nil,
		RepetitionPenalty: nil,
		PresencePenalty:   nil,
		FrequencyPenalty:  nil,
		Stage:             proto.BusinessStage_GENERATION,
		SecurityConfig: &conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
		ExtraBody: map[string]interface{}{
			"thinking": map[string]string{"type": "disabled"},
		},
		UseSystemPromptPrefixCache: false,
		ModelApi:                   conf.ModelApiResponses,
	},
	"virtual-llm-entityword-online": {
		ModelName:     "virtual-llm-entityword-online",
		ContextLength: 16 * 1024,
		IsReferences:  true,
		CiteMaxCount:  5,
		MaxTokens:     lo.ToPtr[int32](2048),
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
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
	"zh-llm-14b-online": {
		ModelName:     "zh-llm-14b-online",
		MaxTokens:     lo.ToPtr[int32](2048),
		ContextLength: 16 * 1024,
		Stop: []string{
			"<|im_end|>",
		},
		Temperature:     lo.ToPtr[float32](0.3),
		TopP:            lo.ToPtr[float32](0.3),
		PresencePenalty: lo.ToPtr[float32](0.5),
		Stage:           proto.BusinessStage_GENERATION,
		SecurityConfig: &conf.SecurityConfig{
			SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
			ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
			Scene:           proto.ChatType_ZHIDA_V2.String(),
		},
	},
}
