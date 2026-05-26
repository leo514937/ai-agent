package conf_stage

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/conf_stage/operation_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

type StageGenerateConfig struct {
	stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
	operationParser *operation_config.CachedParser
}

func (c *StageGenerateConfig) GetConfigMap(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		// 安全审核 answer 与 word
		stream_chat_default_tab_conf.RelevantQuerySecurityReviewLogic: {
			conf.RiskConfigWordSource.ToConvert(): proto.QueryType_RELATE_WORD_QUESTION.String(),
		},
		stream_chat_default_tab_conf.SecurityReviewOutLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:         rpc.RiskCheckSourceSearchAnswer.ToConvert(),
				ChatMappingType:  entities.ChatMappingTypeLLMAnswer.ToConvert(),
				Scene:            proto.ChatType_ZHIDA_MCP.String(),
				ExtraStoreSource: conf.SourceQueryItemLogicStoreKey,
			}.ToJsonString(),
		},
		stream_chat_default_tab_conf.StreamChatLogic: {
			conf.StreamChatDisableReferences: "true",
			conf.StreamChatIsThinkSeparated:  "true",
			conf.StreamChatIsUseThink:        "true",
			conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
				ModelName:          "ds-v3_1-think-zhida-online",
				ContextLength:      64 * 1024,
				ExtraContextLength: 2 * 1024, // 额外上下文长度 用于rerank时 留足buffer
				MaxTokens:          lo.ToPtr[int32](16 * 1024),
				TopP:               lo.ToPtr[float32](0.8),
				IsCiteV2:           false,
				Stage:              proto.BusinessStage_GENERATION,
				SecurityConfig: &conf.SecurityConfig{
					SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
					ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
					Scene:           proto.ChatType_ZHIDA_MCP.String(),
				},
			}.ToJsonString(),
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId: "zhida_v2_reasoning_system",
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryLimit10),
					conf.NewChatMsgConfigByKnowledge("zhida_v2_reasoning_user", "", ""),
				},
			}.ToJsonString(),
		},

		stream_chat_default_tab_conf.ChatLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
				ModelName:     "zhida-doubao-seed-1-6-flash",
				ContextLength: 8 * 1024,
				MaxTokens:     lo.ToPtr[int32](128),
				TopP:          lo.ToPtr[float32](0.8),
				Stage:         proto.BusinessStage_RELEVANT_QUERY,
				ThinkingType:  conf.ThinkingTypeDisabled,
			}.ToJsonString(),
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId: "1304",
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByKnowledge("related_question_v3_user", "", ""),
				},
			}.ToJsonString(),
		},
	}

	intention, _ := requestCtx.DataMap().GetString(ctx, graph_macro.ZagKeyIntention)
	if macro.IntentionType(intention) == macro.GetQueryRouteIdentity() {
		logicConfigMap[stream_chat_default_tab_conf.StreamChatLogic][conf.ChatMessageJsonConfig] = conf.MsgConfig{
			SystemPromptId: "zhida_v2_wru_system",
			// config 顺序 决定 msg 的拼接顺序
			MsgConfigArr: []conf.ChatMsgConfig{
				conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryNewLimit),
				conf.NewChatMsgConfigByQuery(),
			},
		}.ToJsonString()
		logicConfigMap[stream_chat_default_tab_conf.ChatLogic][conf.ChatDisable] = "true"
	}

	return logicConfigMap
}
