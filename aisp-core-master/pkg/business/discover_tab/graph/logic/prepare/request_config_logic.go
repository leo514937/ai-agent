package prepare

import (
	"context"
	"encoding/json"
	"strings"

	apollo "git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank/rerank_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/preparer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 处理配置
type RequestConfigLogic struct {
	*preparer.PreparerLogic[entities.RequestContext, entities.User, entities.Item, requestConfig]
}

type requestConfig struct {
	abParams       map[zlab.SceneId]map[string]string
	logicConfigMap map[string]map[string]string
}

func NewRequestConfigLogic(name string, config map[string]string) *RequestConfigLogic {
	res := &RequestConfigLogic{
		PreparerLogic: preparer.NewPreparerLogic[entities.RequestContext, entities.User, entities.Item, requestConfig](name, config),
	}

	res.FillUserFunc = res.getRequestConfig
	res.MergeUserFunc = res.setRequestConfig
	return res
}

type OutSiteRecallMergeConfig struct {
	TopK           int     `json:"recall_merge_topk"`
	ScoreThreshold float32 `json:"recall_merge_score_threshold"`
}

func (r *RequestConfigLogic) getRequestConfig(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) (requestConfig, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "root.RequestConfigLogic.getRequestConfig")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	logger := log.WithField(ctx, "getRecallOption", "")

	config := requestConfig{
		abParams:       map[zlab.SceneId]map[string]string{},
		logicConfigMap: requestCtx.GetBizContext().GetLogicConfigMap(),
	}

	// 重置召回 merge 配置
	outSiteRecallMergeConfig := &OutSiteRecallMergeConfig{}
	apollo.MustGetJson(macro.OutSiteRecallMergeConfigName, outSiteRecallMergeConfig)
	if config.logicConfigMap[stream_chat_default_tab_conf.KbRecallOutSiteSourceMergeLogic] != nil {
		if outSiteRecallMergeConfig.TopK != 0 {
			config.logicConfigMap[stream_chat_default_tab_conf.KbRecallOutSiteSourceMergeLogic][conf.RecallMergeTopK] = cast.ToString(outSiteRecallMergeConfig.TopK)
		}
		if outSiteRecallMergeConfig.ScoreThreshold != 0 {
			config.logicConfigMap[stream_chat_default_tab_conf.KbRecallOutSiteSourceMergeLogic][conf.RecallMergeScoreThreshold] = cast.ToString(outSiteRecallMergeConfig.ScoreThreshold)
		}
	}

	// 如果是预览模式下 则关闭重答缓存
	if requestCtx.GetBizContext().RequestHeader() != nil &&
		lo.Contains(stream_chat_default_tab_conf.NotAllowRetryAnswerTrafficSource, requestCtx.GetBizContext().GetTrafficSource()) {
		caseConfig := requestCtx.GetBizContext().GetRunCaseConfig()
		caseConfig.IsUseSessionCache = false
		caseConfig.IsSaveSessionCache = false
		requestCtx.GetBizContext().SetRunCaseConfig(caseConfig)
	}

	// 如果接口指定了 model 参数则覆盖
	if requestCtx.GetBizContext().GetChatExtraInfo() != nil && requestCtx.GetBizContext().GetChatExtraInfo().GetModelArgs() != nil {
		modelArgs := requestCtx.GetBizContext().GetChatExtraInfo().GetModelArgs()
		// 获取chat配置，并修改一些 可修改的参数
		chatConfigStr := requestCtx.GetBizContext().GetLogicConfig(stream_chat_default_tab_conf.StreamChatLogic, conf.JsonConfigLogicKey.ToConvert())
		chatConfig := conf.ChatConfig{}
		msgConfigErr := json.Unmarshal([]byte(chatConfigStr), &chatConfig)
		if msgConfigErr == nil {
			if modelArgs.GetMaxTokens() != nil {
				chatConfig.MaxTokens = lo.ToPtr[int32](modelArgs.GetMaxTokens().GetValue())
			}
			if modelArgs.GetTemperature() != nil {
				chatConfig.Temperature = lo.ToPtr[float32](modelArgs.GetTemperature().GetValue())
			}
			if modelArgs.GetTopK() != nil {
				chatConfig.TopK = lo.ToPtr[int32](modelArgs.GetTopK().GetValue())
			}
			if modelArgs.GetTopP() != nil {
				chatConfig.TopP = lo.ToPtr[float32](modelArgs.GetTopP().GetValue())
			}
			if modelArgs.GetPresencePenalty() != nil {
				chatConfig.PresencePenalty = lo.ToPtr[float32](modelArgs.GetPresencePenalty().GetValue())
			}
			if modelArgs.GetRepetitionPenalty() != nil {
				chatConfig.RepetitionPenalty = lo.ToPtr[float32](modelArgs.GetRepetitionPenalty().GetValue())
			}
			if len(modelArgs.GetStop()) > 0 {
				chatConfig.Stop = modelArgs.GetStop()
			}
			config.logicConfigMap[stream_chat_default_tab_conf.StreamChatLogic][conf.JsonConfigLogicKey.ToConvert()] = chatConfig.ToJsonString()
		}
	}

	// 直答站内流量来源
	zhidaInnerTrafficSource := []proto.TrafficSource{proto.TrafficSource_undefined_traffic, proto.TrafficSource_zhida}
	// 如果是 直答流量来源 则 需要判断简洁和深入模式不同的 prompt 变动
	// 如果是 非直答流量来源 则默认 chat 简洁模式 且 有新的算法策略
	if requestCtx.GetBizContext().GetBizType() == proto.ChatType_ZHIDA_TAB.String() && requestCtx.GetBizContext().RequestHeader() != nil {

		// 站外引流流量 需要匹配专属配置
		if !lo.Contains(zhidaInnerTrafficSource, requestCtx.GetBizContext().RequestHeader().GetTrafficSource()) {
			graphLogicConfig, _ := conf.GetGraphConfig(conf.BuildLogicConfigName(requestCtx.GetBizContext().GetApi(), requestCtx.GetBizContext().GetBizType()))
			overwriteBizConfigMap := graphLogicConfig.GetOverwriteBizConfigMapByTraffic(
				requestCtx.GetBizContext().RequestHeader().GetTrafficSource(),
				requestCtx.GetBizContext().RequestHeader().GetClientSource(),
			)
			r.overwriteLogicConfig(config, overwriteBizConfigMap)
		}

		if r.isEnableCacheTrafficSource(requestCtx.GetBizContext().RequestHeader().GetTrafficSource()) {
			requestCtx.GetBizContext().SetEnableCache(true)
		}

		// 获取chat配置，不论是zhida 还是 引流，都需要根据接口传入的chat_style来设置不同的prompt
		chatMsgConfigStr := requestCtx.GetBizContext().GetLogicConfig(stream_chat_default_tab_conf.StreamChatLogic, conf.ChatMessageJsonConfig)
		chatMsgConfig := conf.MsgConfig{}
		msgConfigErr := json.Unmarshal([]byte(chatMsgConfigStr), &chatMsgConfig)
		if msgConfigErr == nil && !chatMsgConfig.IsCustom {
			switch requestCtx.GetBizContext().GetChatStyle() {
			case proto.ChatStyle_SIMPLE:
				chatMsgConfig.SystemPromptId = "zhida_summary_system_concise"
			case proto.ChatStyle_THOROUGH:
				chatMsgConfig.SystemPromptId = "zhida_summary_system_elaborated"
			}
		}
		if requestCtx.GetBizContext().GetTrafficSource() == proto.TrafficSource_zhida_gr_demo {
			chatMsgConfig.SystemPromptTag = "gov_rel" // 政府关系 system prompt 不用 .default，用 .gov_rel
			config.logicConfigMap[stream_chat_default_tab_conf.AgentOverwriteConfigLogic][conf.OverwriteStrategyExp] = "gr"
		}
		config.logicConfigMap[stream_chat_default_tab_conf.StreamChatLogic][conf.ChatMessageJsonConfig] = chatMsgConfig.ToJsonString()

		// 如果指定深度思考模式，则对于知识查询，更换为 deepseek-r1 模型
		if requestCtx.GetBizContext().GetChatStyle() == proto.ChatStyle_DEEP_THINKING {
			systemPromptId := "zhida_summary_system_reasoning"
			modelName := "ds-r1-full-awq-online"
			query := requestCtx.GetBizContext().RequestMessage().GetText()
			if apollo.GetBool(macro.UseEasterEgg, false) && (strings.HasPrefix(query, "如何评价") || strings.HasPrefix(query, "如何看待")) {
				systemPromptId = "zhida_summary_system_reasoning_xieyao"
				modelName = "ds-r1-full-awq-online-full"
			}
			config.logicConfigMap[stream_chat_default_tab_conf.StreamChatLogic] = map[string]string{
				conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
					ModelName:    modelName,
					IsReferences: true,
					MaxTokens:    lo.ToPtr[int32](8192),
					Temperature:  lo.ToPtr[float32](0.7),
					TopP:         lo.ToPtr[float32](0.8),
					Stage:        proto.BusinessStage_GENERATION,
					SecurityConfig: &conf.SecurityConfig{
						SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
						ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
						Scene:           proto.ChatType_ZHIDA_TAB.String(),
					},
				}.ToJsonString(),
				conf.ChatMessageJsonConfig: conf.MsgConfig{
					SystemPromptId:              systemPromptId,
					SystemDefaultPromptTemplate: conf.PromptCoderQuery,
					// config 顺序 决定 msg 的拼接顺序
					MsgConfigArr: []conf.ChatMsgConfig{
						conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryLimit),
						conf.NewChatMsgConfigByKnowledge("zhida_summary_user_reasoning", conf.PromptByQwenUser, ""),
					},
				}.ToJsonString(),
				conf.StreamChatIsUseThink: "true",
			}
			config.logicConfigMap[stream_chat_default_tab_conf.Recall2ModelChunkAndScoreLogic][conf.JsonConfigLogicKey.ToConvert()] = util.GetJSONIgnoreError(conf.RecallChunkReRankConfig{
				KeySize:                    512,
				KeyStep:                    256,
				KeyOffset:                  0.5,
				ValueSize:                  1024,
				TotalSize:                  54 * 1024,
				ScoreThreshold:             0.1,
				BoundaryRegex:              rerank_util.BoundaryRegexBySentence,
				ActualChunkSizeLimitPerDoc: 2048,
			})
			config.logicConfigMap[stream_chat_default_tab_conf.AgentOverwriteConfigLogic][conf.OverwriteConfigStrategy] = "kb_deep_thinking"
			config.logicConfigMap[stream_chat_default_tab_conf.AgentOverwriteConfigLogic2][conf.OverwriteConfigStrategy] = "kb_deep_thinking"
		}
	}

	if requestCtx.GetBizContext().GetBizType() == proto.ChatType_ZPLUS_BRAND.String() {
		brandNames := requestCtx.GetBizContext().GetExtraInfo().GetBrandName()
		if brandNames != nil && len(brandNames) > 0 {
			configStr := apollo.GetStringByNamespace(macro.ZplusApolloNamespace, macro.BrandQueryRouteConfigName, "")
			if configStr != "" {
				var brandQueryRouteConfig map[string]conf.RouteConfig
				err := json.Unmarshal([]byte(configStr), &brandQueryRouteConfig)
				if err == nil {
					routeConfig, ok := brandQueryRouteConfig[brandNames[0]]
					if ok {
						overwriteConfigMap := map[string]map[string]string{
							stream_chat_default_tab_conf.QueryRouterLogic: {
								conf.JsonConfigLogicKey.ToConvert(): routeConfig.ToJsonString(),
							},
						}
						r.overwriteLogicConfig(config, overwriteConfigMap)
					}
				}
			}
		}
	}

	// 填充 ab 实验参数
	for sceneId, zlabParams := range requestCtx.GetBizContext().GetAbParamMap() {
		for _, zlabParam := range zlabParams {
			abContext := requestCtx.GetBizContext().GetABContext(sceneId)
			abValue := abContext.GetZlabABValue(zlabParam)
			if _, exist := config.abParams[sceneId]; !exist {
				config.abParams[sceneId] = map[string]string{}
			}
			config.abParams[sceneId][zlabParam.Key] = abValue
		}
	}

	// 如果是跑 case 模式，覆盖相关配置
	if requestCtx.GetBizContext().GetRunCaseConfig().IsOpen {
		for logicName, configMap := range requestCtx.GetBizContext().GetRunCaseConfig().LogicConfig {
			for configKey, configValue := range configMap {
				if config.logicConfigMap[logicName] == nil {
					config.logicConfigMap[logicName] = make(map[string]string)
				}
				config.logicConfigMap[logicName][configKey] = configValue
			}
		}
	}

	logger.Infof(ctx, "logicConfig:%s, abParam:%s", util.GetJSONIgnoreError(config.logicConfigMap), util.GetJSONIgnoreError(config.abParams))
	constant.DataOutputNodeLog.Infof(logCtx, "logicConfig:%s, abParam:%s", util.GetJSONIgnoreError(config.logicConfigMap), util.GetJSONIgnoreError(config.abParams))

	return config, nil
}

func isAppZhida(requestContext *entities.RequestContext) bool {
	return requestContext.GetBizType() == proto.ChatType_DISCOVER_TAB.String() ||
		(requestContext.GetBizType() == proto.ChatType_ZHIDA_TAB.String() &&
			requestContext.RequestHeader() != nil &&
			requestContext.RequestHeader().GetClientSource() == proto.ClientSource_ZHIHU_APP)
}

func isPcZhida(requestContext *entities.RequestContext) bool {
	return requestContext.GetBizType() == proto.ChatType_ZHIDA_TAB.String() &&
		requestContext.RequestHeader() != nil &&
		requestContext.RequestHeader().GetClientSource() == proto.ClientSource_PC_WEB
}

func (r *RequestConfigLogic) setRequestConfig(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], config requestConfig) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.RequestConfigLogic.setRequestConfig")
	defer span.Finish()

	for scene, abParamValue := range config.abParams {
		for key, value := range abParamValue {
			requestCtx.GetBizContext().AddAbParamValue(scene, key, value)
		}
	}
	if len(config.logicConfigMap) > 0 {
		requestCtx.GetBizContext().SetLogicConfigMap(config.logicConfigMap)
	}
	return nil
}

func (r *RequestConfigLogic) overwriteLogicConfig(originConfig requestConfig, overwriteConfigMap map[string]map[string]string) {
	baseLogicConfigMap := originConfig.logicConfigMap

	for logicName, config := range overwriteConfigMap {
		for configKey, configValue := range config {
			if baseLogicConfigMap[logicName] == nil {
				baseLogicConfigMap[logicName] = make(map[string]string)
			}
			baseLogicConfigMap[logicName][configKey] = configValue
		}
	}
}

func (r *RequestConfigLogic) isEnableCacheTrafficSource(source proto.TrafficSource) bool {
	ZhidaDisableCacheTrafficSource := apollo.GetStringArray(macro.ZhidaDisableCacheTrafficSource, ",", []string{})
	return !lo.Contains(ZhidaDisableCacheTrafficSource, source.String())
}
