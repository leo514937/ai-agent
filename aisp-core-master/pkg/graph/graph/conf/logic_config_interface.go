package conf

import (
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
)

var (
	LogicConfigNameByPcDiscoverTab          = BuildLogicConfigName(graph_constant.ApiStreamChat, proto.ChatType_PC_DISCOVER_TAB.String())
	LogicConfigNameByDiscoverTab            = BuildLogicConfigName(graph_constant.ApiStreamChat, proto.ChatType_DISCOVER_TAB.String())
	LogicConfigNameByZhiDaTab               = BuildLogicConfigName(graph_constant.ApiStreamChat, proto.ChatType_ZHIDA_TAB.String())
	LogicConfigNameByZhiDaProTab            = BuildLogicConfigName(graph_constant.ApiStreamChat, proto.ChatType_ZHIDA_PRO_TAB.String())
	LogicConfigNameByZplusBrand             = BuildLogicConfigName(graph_constant.ApiStreamChat, proto.ChatType_ZPLUS_BRAND.String())
	LogicConfigNameByQueriesZhiDaTabGuid    = BuildLogicConfigName(graph_constant.ApiSuggestQueries, proto.SuggestQueriesType_ZHIDA_TAB_GUIDE.String())
	LogicConfigNameByQueriesDiscoverTabGuid = BuildLogicConfigName(graph_constant.ApiSuggestQueries, proto.SuggestQueriesType_DISCOVER_TAB_GUIDE.String())
	LogicConfigNameByQueriesAnswerAsk       = BuildLogicConfigName(graph_constant.ApiSuggestQueries, proto.SuggestQueriesType_ASK_AGAIN_RELATED.String())
	LogicConfigNameByQueriesSpecifiedDoc    = BuildLogicConfigName(graph_constant.ApiSuggestQueries, proto.SuggestQueriesType_SPECIFIED_DOC_RELATED.String())
	LogicConfigNameByQueriesSearchAsk       = BuildLogicConfigName(graph_constant.ApiSuggestQueries, proto.SuggestQueriesType_SEARCH_ASK_AGAIN_RELATED.String())
	LogicConfigNameByQueryMerge             = BuildLogicConfigName(graph_constant.ApiBuildQuery, "all")
	LogicConfigNameByAIDaily                = BuildLogicConfigName(graph_constant.ApiAIDailyPlaylist, "all")
)

func BuildLogicConfigName(apiName string, bizType string) string {
	return fmt.Sprintf("%s:%s", apiName, bizType)
}

type LogicConfig interface {
	// GetGraphBizType 获取Graph 当前图名称
	GetGraphBizType() string

	// GetBizConfigMap 获取业务配置
	GetBizConfigMap() map[string]map[string]string

	// GetAbParamMap 获取AB参数Map
	GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue

	GetOverwriteStrategyId(agent string, exps ...string) string
	GetOverwriteBizConfigMap(agent string) map[string]map[string]string

	GetOverwriteBizConfigMapByTraffic(traffic proto.TrafficSource, client proto.ClientSource) map[string]map[string]string
}

var allGraphConfig = map[string]LogicConfig{}

func RegisterLogicConfig(logicConfig LogicConfig) {
	_, exit := allGraphConfig[logicConfig.GetGraphBizType()]
	if exit {
		panic("exist logic config name:" + logicConfig.GetGraphBizType())
	}
	allGraphConfig[logicConfig.GetGraphBizType()] = logicConfig
}

func GetGraphConfig(graphBizType string) (LogicConfig, bool) {
	logicConfig, isExist := allGraphConfig[graphBizType]
	return logicConfig, isExist
}
