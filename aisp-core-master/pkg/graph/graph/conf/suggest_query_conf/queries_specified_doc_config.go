package suggest_query_conf

import (
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
)

func init() {
	conf.RegisterLogicConfig(&QueriesSpecifiedDocLogicConfig{})
}

type QueriesSpecifiedDocLogicConfig struct {
	conf.LogicConfig
}

// GetGraphBizType 获取Graph 当前图名称
func (c *QueriesSpecifiedDocLogicConfig) GetGraphBizType() string {
	return conf.LogicConfigNameByQueriesSpecifiedDoc
}

// GetBizConfigMap 获取业务配置
func (c *QueriesSpecifiedDocLogicConfig) GetBizConfigMap() map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		RelatedWordSecurityReviewLogic: {conf.RiskConfigWordSource.ToConvert(): proto.QueryType_RELATE_WORD_QUESTION.String()},
	}
	return logicConfigMap
}

// GetAbParamMap 获取AB参数Map
// 把该 graph 涉及的实验的 base 组放到这里，用于打点
func (c *QueriesSpecifiedDocLogicConfig) GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue {
	return map[zlab.SceneId][]zlab.ZlabValue{}
}

func (c *QueriesSpecifiedDocLogicConfig) GetOverwriteStrategyId(agent string, exps ...string) string {
	return strings.Join(append([]string{agent}, exps...), "_")
}

func (c *QueriesSpecifiedDocLogicConfig) GetOverwriteBizConfigMap(agent string) map[string]map[string]string {
	return map[string]map[string]string{}
}

func (c *QueriesSpecifiedDocLogicConfig) GetOverwriteBizConfigMapByTraffic(traffic proto.TrafficSource, client proto.ClientSource) map[string]map[string]string {
	return map[string]map[string]string{}
}
