package stage_handler

import (
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"github.com/samber/lo"
)

var (
	GraphLogicConfigNameByZhiDaV2         = BuildGraphLogicConfigName(graph_constant.ApiStreamChat, proto.ChatType_ZHIDA_V2.String())
	GraphLogicConfigNameByZhiDaAgent      = BuildGraphLogicConfigName(graph_constant.ApiStreamChat, proto.ChatType_ZHIDA_AGENT.String())
	GraphLogicConfigNameByRecall          = BuildGraphLogicConfigName(graph_constant.ApiRecall, proto.ChatType_ZHIDA_V2.String())
	GraphLogicConfigNameByDeepSearch      = BuildGraphLogicConfigName(graph_constant.ApiDeepSearch, proto.ChatType_ZHIDA_V2.String())
	GraphLogicConfigNameByDirectChatSub   = BuildGraphLogicConfigName(graph_constant.ApiStreamChatSub, proto.ChatType_ZHIDA_AGENT.String())
	GraphLogicConfigNameByResearchChatSub = BuildGraphLogicConfigName(graph_constant.ApiResearchStreamChatSub, proto.ChatType_ZHIDA_AGENT.String())
	GraphLogicConfigNameByZhiDaMCP        = BuildGraphLogicConfigName(graph_constant.ApiStreamChat, proto.ChatType_ZHIDA_MCP.String())
)

func BuildGraphLogicConfigName(apiName string, bizType string) string {
	return fmt.Sprintf("%s:%s:stage_config", apiName, bizType)
}

var allGraphStageConfig = map[string]stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item]{}

func RegisterStageLogicConfig(logicConfig stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item]) {
	_, exit := allGraphStageConfig[logicConfig.GetGraphBizType()]
	if exit {
		panic("exist logic config name:" + logicConfig.GetGraphBizType())
	}
	allGraphStageConfig[logicConfig.GetGraphBizType()] = logicConfig
}

func RegisterRecallStageLogicConfig(logicConfig stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item]) {
	_, exit := allGraphStageConfig[logicConfig.GetRecallGraphBizType()]
	if exit {
		panic("exist logic config name:" + logicConfig.GetRecallGraphBizType())
	}
	allGraphStageConfig[logicConfig.GetRecallGraphBizType()] = logicConfig
}

func RegisterDeepSearchStageLogicConfig(logicConfig stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item]) {
	_, exit := allGraphStageConfig[logicConfig.GetDeepSearchGraphBizType()]
	if exit {
		panic("exist logic config name:" + logicConfig.GetDeepSearchGraphBizType())
	}
	allGraphStageConfig[logicConfig.GetDeepSearchGraphBizType()] = logicConfig
}

func GetGraphStageConfig(graphBizType string) (stage_config.GraphStageLogicConfig[entities.RequestContext, entities.User, entities.Item], bool) {
	logicConfig, isExist := allGraphStageConfig[graphBizType]
	return logicConfig, isExist
}

// OverrideGraphStageConfig 增量覆盖合并config
func OverrideGraphStageConfig(sourceConfigMap map[string]map[string]string, newConfigMap map[string]map[string]string) map[string]map[string]string {
	if sourceConfigMap == nil || newConfigMap == nil {
		return lo.Ternary(sourceConfigMap == nil, newConfigMap, sourceConfigMap)
	}
	// 1. 保留sourceConfigMap中存在的配置，直接新增newConfigMap中不存在的配置
	for logicName, logicConfigMap := range newConfigMap {
		_, isExist := sourceConfigMap[logicName]
		if isExist {
			continue
		}
		sourceConfigMap[logicName] = logicConfigMap
	}
	// 2. 覆盖算子配置
	for logicName, logicConfigMap := range sourceConfigMap {
		newLogicMap, isExist := newConfigMap[logicName]
		if !isExist {
			continue
		}
		sourceConfigMap[logicName] = util.OverrideMap(logicConfigMap, newLogicMap)
	}
	return sourceConfigMap
}
