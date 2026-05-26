package query_merge_conf

import (
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
)

const (
	// stage
	RootStage     = "root"
	PrepareStage  = "prepare"
	EmptyStage    = "emptyStage"
	MappingStage  = "mapping"
	SecurityStage = "security"
	RespStage     = "resp"

	// logic
	UserMessageLogic       = "UserMessage"
	ChatHistoryLogic       = "ChatHistory"
	EmptyLogic             = "empty"
	QueryMergeLogic        = "QueryMerge"
	SecurityReviewOutLogic = "securityReviewOut"
	SecurityPostLogic      = "securityPost"
	ItemRespLogic          = "ItemResp"
)

// GetStaticConfigMap 获取静态配置
var StaticConfigMap = map[string]map[string]string{}

func init() {
	conf.RegisterLogicConfig(&QueryMergeTabLogicConfig{})
}

type QueryMergeTabLogicConfig struct {
	conf.LogicConfig
}

// GetGraphBizType 获取Graph 当前图名称
func (c *QueryMergeTabLogicConfig) GetGraphBizType() string {
	return conf.LogicConfigNameByQueryMerge
}

// GetBizConfigMap 获取业务配置
func (c *QueryMergeTabLogicConfig) GetBizConfigMap() map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		SecurityReviewOutLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.SecurityConfig{
				SourceId:        rpc.RiskCheckSourceSearchQueryAndMerge.ToConvert(),
				ChatMappingType: entities.ChatMappingTypeQueryMerge.ToConvert(),
				Scene:           proto.ChatType_SEARCH_TAB.String(),
			}.ToJsonString(),
		},
	}
	return logicConfigMap
}

// GetAbParamMap 获取AB参数Map
// 把该 graph 涉及的实验的 base 组放到这里，用于打点
func (c *QueryMergeTabLogicConfig) GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue {
	return map[zlab.SceneId][]zlab.ZlabValue{}
}

func (c *QueryMergeTabLogicConfig) GetOverwriteStrategyId(agent string, exps ...string) string {
	return strings.Join(append([]string{agent}, exps...), "_")
}

func (c *QueryMergeTabLogicConfig) GetOverwriteBizConfigMap(agent string) map[string]map[string]string {
	return map[string]map[string]string{}
}

func (c *QueryMergeTabLogicConfig) GetOverwriteBizConfigMapByTraffic(traffic proto.TrafficSource, client proto.ClientSource) map[string]map[string]string {
	return map[string]map[string]string{}
}
