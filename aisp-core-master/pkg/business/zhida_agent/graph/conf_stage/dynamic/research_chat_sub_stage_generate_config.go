package dynamic

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/conf_stage/operation_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

func NewResearchChatSubStageGenerateConfig() *ResearchChatSubStageGenerateConfig {
	return &ResearchChatSubStageGenerateConfig{
		modelConfigDict: map[string]conf.ChatConfig{
			"zhida-doubao-seed-1-6": {
				ModelName:          "zhida-doubao-seed-1-6",
				IsReferences:       true,
				CiteMaxCount:       5,
				ContextLength:      256 * 1024,
				ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
				MaxTokens:          lo.ToPtr[int32](32 * 1024),
				TopP:               lo.ToPtr[float32](0.8),
				Stage:              proto.BusinessStage_GENERATION,
				ThinkingType:       conf.ThinkingTypeDisabled,
				SecurityConfig: &conf.SecurityConfig{
					SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
					ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
					Scene:           proto.ChatType_ZHIDA_V2.String(),
				},
			},
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
		},
	}
}

type ResearchChatSubStageGenerateConfig struct {
	stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
	operationParser *operation_config.CachedParser
	modelConfigDict map[string]conf.ChatConfig
}

func (c *ResearchChatSubStageGenerateConfig) GetConfigMap(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		// 安全审核 answer 与 word
		stream_chat_default_tab_conf.RelevantQuerySecurityReviewLogic: {conf.RiskConfigWordSource.ToConvert(): proto.QueryType_RELATE_WORD_QUESTION.String()},
		stream_chat_default_tab_conf.SecurityReviewOutLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:         rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:            proto.ChatType_ZHIDA_V2.String(),
				ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
			}.ToJsonString(),
		},
		// 存储query 缓存
		stream_chat_default_tab_conf.SaveQueryResultLogic: {
			// 默认只开启预制词缓存
			conf.ChatQueryCacheIsOnlyPrefabWord.ToConvert(): cast.ToString(false),
		},

		stream_chat_default_tab_conf.ChatLogic: {
			conf.ChatDisable: "true", // 默认关闭相关词输出
		},
	}

	mainCustomConfig := c.GetMainCustomConfig(ctx, requestCtx, user)
	// 覆盖更新config
	logicConfigMap = stage_handler.OverrideGraphStageConfig(logicConfigMap, mainCustomConfig)
	return logicConfigMap
}

// GetMainCustomConfig 获得主配置
func (c *ResearchChatSubStageGenerateConfig) GetMainCustomConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// 模型基础配置
	chatBaseConfig := c.getZhiDaAgentModel(requestCtx)
	// 是否禁用相关词
	isDisableRelateQueries := "false"
	// 是否禁止角标输出
	isDisableReferences := "false"
	// 思考模式下 是否分离think
	isThink := "false"
	isThinkSeparated := "true"
	// 默认 prompt
	defSystemPromptId := "zhida_agent_research_system"

	// 如果最后一位不是 tool 类型，则表示无召回内容 需要变更prompt为直接回答
	lastMsg := lo.LastOrEmpty(requestCtx.GetBizContext().GetMessages())
	if lastMsg != nil && lastMsg.Role != dto.ChatRequestMessageRoleToolOutPut {
		defSystemPromptId = "zhida_agent_direct_reply_system"
	}

	chatMsgConfig := conf.MsgConfig{
		SystemPromptId: defSystemPromptId,
	}.ToJsonString()

	return map[string]map[string]string{
		stream_chat_default_tab_conf.StreamChatLogic: {
			conf.StreamChatDisableReferences:    isDisableReferences,
			conf.JsonConfigLogicKey.ToConvert(): chatBaseConfig,
			conf.ChatMessageJsonConfig:          chatMsgConfig,
			conf.StreamChatIsThinkSeparated:     isThinkSeparated,
			conf.StreamChatIsUseThink:           cast.ToString(isThink),
		},
		stream_chat_default_tab_conf.ChatLogic: {
			conf.ChatDisable:                    isDisableRelateQueries,
			conf.JsonConfigLogicKey.ToConvert(): c.modelConfigDict["question-gen-14b"].ToJsonString(),
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId: "1304",
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByKnowledge("related_question_v3_user", "", ""),
				},
			}.ToJsonString(),
		},
	}
}

func (c *ResearchChatSubStageGenerateConfig) getZhiDaAgentModel(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	// 如果是 zhida v2 版本则开启思考分离
	isCiteV2 := requestCtx.GetBizContext().RequestHeader().Version == graph_constant.ZhiDaV2Version
	modelName := "zhida-doubao-seed-1-6"
	modelConfig := c.modelConfigDict[modelName]
	modelConfig.IsCiteV2 = isCiteV2
	return modelConfig.ToJsonString()
}
