package conf_stage

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
)

type ResearchChatSubLogicConfig struct {
	stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item]
	requestCtx            *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]
	user                  *data_frame.UserData[entities.User]
	dynamicStageConfigMap map[conf.StageType]stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
}

// GetGraphBizType 获取Graph 当前图名称
func (c *ResearchChatSubLogicConfig) GetGraphBizType() string {
	return stage_handler.GraphLogicConfigNameByResearchChatSub
}

// GetRecallGraphBizType 获取召回图名称
func (c *ResearchChatSubLogicConfig) GetRecallGraphBizType() string {
	return ""
}

// GetDeepSearchGraphBizType 获取深度搜索图名称
func (c *ResearchChatSubLogicConfig) GetDeepSearchGraphBizType() string {
	return ""
}

// GetDefaultBizConfigMap 获取默认配置
func (c *ResearchChatSubLogicConfig) GetDefaultBizConfigMap() map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		stream_chat_default_tab_conf.GenerateConfigLogic: {
			conf.StageTypeConfig: conf.StageTypeGenerate.String(),
		},
	}
	return logicConfigMap
}

func (c *ResearchChatSubLogicConfig) GetDynamicBizLogicConfig(
	ctx context.Context,
	stageType conf.StageType,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) map[string]map[string]string {
	stageLogicConfig, isExist := c.dynamicStageConfigMap[stageType]
	if !isExist {
		return map[string]map[string]string{}
	}
	return stageLogicConfig.GetConfigMap(ctx, requestCtx, user)
}

// GetAbParamMap 获取AB参数Map
// 把该 graph 涉及的实验的 base 组放到这里，用于打点
func (c *ResearchChatSubLogicConfig) GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue {
	return map[zlab.SceneId][]zlab.ZlabValue{
		macro.ZlabSceneIdAiRecDomain: {},
	}
}
