package suggest_query_conf

import (
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

func init() {
	conf.RegisterLogicConfig(&QueriesAnswerAskLogicConfig{})
}

type QueriesAnswerAskLogicConfig struct {
	conf.LogicConfig
}

// GetGraphBizType 获取Graph 当前图名称
func (c *QueriesAnswerAskLogicConfig) GetGraphBizType() string {
	return conf.LogicConfigNameByQueriesAnswerAsk
}

// GetBizConfigMap 获取业务配置
func (c *QueriesAnswerAskLogicConfig) GetBizConfigMap() map[string]map[string]string {
	logicConfigMap := map[string]map[string]string{
		RelatedWordGetCacheLogic: {
			conf.RelatedWordIsUseCache.ToConvert(): cast.ToString(true),
			// 缓存如果为空 则默认不在继续生成
			conf.RelatedWordCacheNilIsGenerate.ToConvert(): cast.ToString(false),
		},
		RelatedWordChatGenerateLogic: {
			conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
				ModelName: "question-gen-14b",
				MaxTokens: lo.ToPtr[int32](128),
				Stop: []string{
					"<|im_end|>",
					"<|endoftext|>",
				},
				TopP:             lo.ToPtr[float32](0.8),
				Temperature:      lo.ToPtr[float32](0.5),
				PresencePenalty:  lo.ToPtr[float32](0.5),
				FrequencyPenalty: lo.ToPtr[float32](0.0),
				Stage:            proto.BusinessStage_RELEVANT_QUERY,
			}.ToJsonString(),
			conf.ChatMessageJsonConfig: conf.MsgConfig{
				SystemPromptId: "1304",
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByKnowledge("1303", conf.PromptByRelevantQuery, ""),
				},
			}.ToJsonString(),
		},
		RelatedWordSecurityReviewLogic: {conf.RiskConfigWordSource.ToConvert(): proto.QueryType_RELATE_WORD_QUESTION.String()},
	}
	return logicConfigMap
}

// GetAbParamMap 获取AB参数Map
// 把该 graph 涉及的实验的 base 组放到这里，用于打点
func (c *QueriesAnswerAskLogicConfig) GetAbParamMap() map[zlab.SceneId][]zlab.ZlabValue {
	return map[zlab.SceneId][]zlab.ZlabValue{}
}

func (c *QueriesAnswerAskLogicConfig) GetOverwriteStrategyId(agent string, exps ...string) string {
	return strings.Join(append([]string{agent}, exps...), "_")
}

func (c *QueriesAnswerAskLogicConfig) GetOverwriteBizConfigMap(agent string) map[string]map[string]string {
	return map[string]map[string]string{}
}

func (c *QueriesAnswerAskLogicConfig) GetOverwriteBizConfigMapByTraffic(traffic proto.TrafficSource, client proto.ClientSource) map[string]map[string]string {
	return map[string]map[string]string{}
}
