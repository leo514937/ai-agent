package conf_stage

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_agent/graph/conf_stage/dynamic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
)

func init() {
	stage_handler.RegisterStageLogicConfig(&ZhiDaAgentLogicConfig{
		dynamicStageConfigMap: map[conf.StageType]stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]{
			conf.StageTypeInit: dynamic.NewZhiDaAgentStageInitConfig(),
		},
	})

	stage_handler.RegisterStageLogicConfig(&DirectChatSubLogicConfig{
		dynamicStageConfigMap: map[conf.StageType]stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]{
			conf.StageTypeGenerate: dynamic.NewDirectChatSubStageGenerateConfig(),
		},
	})

	stage_handler.RegisterStageLogicConfig(&ResearchChatSubLogicConfig{
		dynamicStageConfigMap: map[conf.StageType]stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]{
			conf.StageTypeGenerate: dynamic.NewResearchChatSubStageGenerateConfig(),
		},
	})
}
