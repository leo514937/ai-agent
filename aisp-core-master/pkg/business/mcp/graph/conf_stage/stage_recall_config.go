package conf_stage

import (
	"context"
	"strings"

	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type StageRecallConfig struct {
	stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
}

func (c *StageRecallConfig) GetConfigMap(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) map[string]map[string]string {
	// 如果是 who are you 意图，则不进行任何召回
	intention, _ := requestCtx.DataMap().GetString(ctx, graph_macro.ZagKeyIntention)
	if macro.IntentionType(intention) == macro.GetQueryRouteIdentity() {
		return map[string]map[string]string{}
	}

	// 仅全网搜召回
	logicConfigMap := map[string]map[string]string{
		stream_chat_default_tab_conf.KbKexinRecallLogic: {
			conf.BaseConfigSkip: "false",
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				KnowledgeBaseType: enums.KnowledgeBaseTypeGlobal,
				RecallSize:        16,
			}),
		},
		stream_chat_default_tab_conf.RecallLimitLogic: {
			conf.RecallMergeMaxTokenField: "16384", // 16k token
		},
		stream_chat_default_tab_conf.RecallSecurityValidContentFetcherLogic: {
			conf.FilterLogicConfByIncludeDocTypeArr: strings.Join([]string{
				aiContent.DocType_Answer.String(),
				aiContent.DocType_Article.String(),
				aiContent.DocType_Link.String(),
			}, ","),
			conf.FilterLogicConfByIsCheckFullContent: "true",
		},
	}

	return logicConfigMap
}
