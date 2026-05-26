package conf_stage

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhida_v2/graph/conf_stage/operation_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources/ab"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
)

func init() {
	stage_handler.RegisterStageLogicConfig(&ChatZhiDaV2LogicConfig{
		dynamicStageConfigMap: map[conf.StageType]stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]{
			conf.StageTypeInit:   &StageInitConfig{},
			conf.StageTypeRecall: &StageRecallConfig{},
			conf.StageTypeReRank: &StageRerankConfig{},
			conf.StageTypeGenerate: &StageGenerateConfig{
				operationParser: operation_config.NewCachedParser(),
			},
		},
	})
	stage_handler.RegisterRecallStageLogicConfig(&ChatZhiDaV2LogicConfig{
		dynamicStageConfigMap: map[conf.StageType]stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]{
			conf.StageTypeRecall: &StageRecallConfig{},
		},
	})

	stage_handler.RegisterDeepSearchStageLogicConfig(&ChatZhiDaV2LogicConfig{
		dynamicStageConfigMap: map[conf.StageType]stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]{
			conf.StageTypeDeepSearch: &StageRecallConfig{},
		},
	})
}

type ChatZhiDaV2LogicConfig struct {
	stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item]
	requestCtx            *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]
	user                  *data_frame.UserData[entities.User]
	dynamicStageConfigMap map[conf.StageType]stage_config.StageLogicConfig[entities.RequestContext, entities.User, entities.Item]
}

// GetGraphBizType 获取Graph 当前图名称
func (c *ChatZhiDaV2LogicConfig) GetGraphBizType() string {
	return stage_handler.GraphLogicConfigNameByZhiDaV2
}

// GetRecallGraphBizType 获取召回图名称
func (c *ChatZhiDaV2LogicConfig) GetRecallGraphBizType() string {
	return stage_handler.GraphLogicConfigNameByRecall
}

// GetDeepSearchGraphBizType 获取深度搜索图名称
func (c *ChatZhiDaV2LogicConfig) GetDeepSearchGraphBizType() string {
	return stage_handler.GraphLogicConfigNameByDeepSearch
}

// GetDefaultBizConfigMap 获取默认配置
func (c *ChatZhiDaV2LogicConfig) GetDefaultBizConfigMap() map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		stream_chat_default_tab_conf.InitConfigLogic: {
			conf.StageTypeConfig: conf.StageTypeInit.String(),
		},
		stream_chat_default_tab_conf.RecallConfigLogic: {
			conf.StageTypeConfig: conf.StageTypeRecall.String(),
		},
		stream_chat_default_tab_conf.RerankConfigLogic: {
			conf.StageTypeConfig: conf.StageTypeReRank.String(),
		},
		stream_chat_default_tab_conf.GenerateConfigLogic: {
			conf.StageTypeConfig: conf.StageTypeGenerate.String(),
		},
	}
	return logicConfigMap
}

func (c *ChatZhiDaV2LogicConfig) GetDynamicBizLogicConfig(
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
func (c *ChatZhiDaV2LogicConfig) GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue {
	return map[zlab.SceneId][]zlab.ZlabValue{
		macro.ZlabSceneIdAiRecDomain: {
			ab.EntitySearchModelDefault,
			ab.QuarkToKexinDefault,
			ab.EntityFlashModelDefault,
		},
	}
}
