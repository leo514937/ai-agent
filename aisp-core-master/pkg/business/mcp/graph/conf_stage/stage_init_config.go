package conf_stage

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

type StageInitConfig struct {
	stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
}

func (c *StageInitConfig) GetConfigMap(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	return map[string]map[string]string{
		stream_chat_default_tab_conf.SecurityReviewLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQuery.ToConvert(),
				Scene:           proto.ChatType_ZHIDA_MCP.String(),
			}.ToJsonString(),
		},
		stream_chat_default_tab_conf.FaqLogic: {
			conf.ConfigFaqSimilarityThreshold: "faq.embeddingSimilarityThreshold",
			conf.ConfigFaqKey:                 string(conf.SearchTabFAQ),
			conf.ConfigFaqMatchTypeKey:        conf.BuildConfigArrayValue(conf.FaqMatchTypeKeywordMatchAll.String(), conf.FaqMatchTypeKeywordMatchAny.String(), conf.FaqMatchTypeEmbeddingSimilarity.String(), conf.FaqMatchTypeFullMatch.String()),
			conf.EmbeddingModelName:           "bge-embedding-ai-zhida-online",
		},
		stream_chat_default_tab_conf.EmptyQueryMergeLogic: {
			conf.QueryMergeSkipAndSetAsQuery: "true",
		},
		stream_chat_default_tab_conf.QueryRouterLogic: {
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(
				conf.RouteConfig{
					IsEnable:              true,
					ModelName:             entities.QueryRouterK2,
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
						macro.GetQueryRouteSearch(),
					},
					DefaultChoice: macro.GetQueryRouteSearch(),
				},
			),
		},
	}
}
