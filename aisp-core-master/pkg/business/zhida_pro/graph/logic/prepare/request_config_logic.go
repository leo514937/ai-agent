package prepare

import (
	"context"
	"encoding/json"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	searchThrift "git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf/stream_chat_default_tab_conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/preparer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 处理配置
type RequestConfigLogic struct {
	*preparer.PreparerLogic[entities.RequestContext, entities.User, entities.Item, requestConfig]
	recallBaseCount           int
	personalKbRecallBaseCount int
}

type requestConfig struct {
	abParams       map[zlab.SceneId]map[string]string
	logicConfigMap map[string]map[string]string
}

func NewRequestConfigLogic(name string, config map[string]string) *RequestConfigLogic {
	res := &RequestConfigLogic{
		PreparerLogic: preparer.NewPreparerLogic[entities.RequestContext, entities.User, entities.Item, requestConfig](name, config),
	}

	res.recallBaseCount = 20
	res.personalKbRecallBaseCount = 16
	res.FillUserFunc = res.getRequestConfig
	res.MergeUserFunc = res.setRequestConfig
	return res
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

	// 学术搜索根据请求参数设置配置
	if requestCtx.GetBizContext().GetBizType() == proto.ChatType_ZHIDA_PRO_TAB.String() {
		/*
			主要是 为了保障召回效果，当用户选择1个召回源时，召回的东西比较少，模型回答的效果不是很理想，所以要做一些扩充召回
			总召回源数 / 当前选择召回源数 得 要放大的倍数
			比如 共3个召唤，
			当前选择了3个，3/3=1  则 召回数为 20*1 不变
			如果选择了1个,   3/1=3  则 召回数为 20*3 放大3倍
		*/
		coefficient := cast.ToFloat32(len(proto.DocKnowledgeBase_value)-1) / cast.ToFloat32(len(requestCtx.GetBizContext().GetAssignmentDocKnowledgeBase()))
		recallCount := cast.ToInt32(cast.ToFloat32(coefficient) * cast.ToFloat32(r.recallBaseCount))
		rumRecallCount := recallCount / 3

		assignmentDocKnowledgeBases := requestCtx.GetBizContext().GetAssignmentDocKnowledgeBase()
		var vertical []searchThrift.Vertical
		for _, assignmentDocKnowledgeBase := range assignmentDocKnowledgeBases {
			// 英文
			if assignmentDocKnowledgeBase == proto.DocKnowledgeBase_KB_ENGLISH {
				config.logicConfigMap[stream_chat_default_tab_conf.KbEnWikiRumRecallLogic] = map[string]string{
					// 因为分别召回 title、content、title+content，此处会扩大3倍，因此先除3，后续可调整
					conf.ConfigRecallSize: cast.ToString(rumRecallCount),
				}
				config.logicConfigMap[stream_chat_default_tab_conf.KbEnWikiRuceneRecallLogic] = map[string]string{
					conf.ConfigRecallSize: cast.ToString(recallCount),
				}
				config.logicConfigMap[stream_chat_default_tab_conf.KbReplenishArxivRecallLogic] = map[string]string{
					conf.ConfigRecallSize: cast.ToString(recallCount),
				}
				config.logicConfigMap[stream_chat_default_tab_conf.KbArxivRecallLogic] = map[string]string{
					conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
						Vertical:               []searchThrift.Vertical{searchThrift.Vertical_ForeignScholar},
						OrderGroup:             0,
						RecallSize:             recallCount,
						NeedNotQueryCorrection: true,
					}),
				}
			}
			// 中文
			if assignmentDocKnowledgeBase == proto.DocKnowledgeBase_KB_CHINESE {
				config.logicConfigMap[stream_chat_default_tab_conf.KbZhWikiRumRecallLogic] = map[string]string{
					// 因为分别召回 title、content、title+content，此处会扩大3倍，因此先给除3，后续可调整
					conf.ConfigRecallSize: cast.ToString(rumRecallCount),
				}
				config.logicConfigMap[stream_chat_default_tab_conf.KbZhWikiRuceneRecallLogic] = map[string]string{
					conf.ConfigRecallSize: cast.ToString(recallCount),
				}
				vertical = append(vertical, searchThrift.Vertical_DomesticScholar)
			}
			// 知乎
			if assignmentDocKnowledgeBase == proto.DocKnowledgeBase_KB_ZHIHU {
				vertical = append(vertical, searchThrift.Vertical_CONTENT)
			}
		}

		// 中文&知乎精选 召回
		var recallSize = recallCount
		if len(vertical) == 0 {
			recallSize = 0
		}
		config.logicConfigMap[stream_chat_default_tab_conf.KbZhihuRecallLogic] = map[string]string{
			conf.JsonConfigLogicKey.ToConvert(): util.GetJSONIgnoreError(conf.ZSearchRecallConfig{
				Vertical:   vertical,
				OrderGroup: 0,
				RecallSize: recallSize,
				OnlyA4p:    true,
			}),
		}

		// ====================================
		// 个人知识库召回
		if len(requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()) > 0 && requestCtx.GetBizContext().RequestHeader().GetTrafficSource() != proto.TrafficSource_internal_qa {
			// 因为分别召回 title、question，此处会扩大2倍，因此先除2，后续可调整
			config.logicConfigMap[stream_chat_default_tab_conf.PersonalKnowledgeBaseRumRecallLogic] = map[string]string{
				conf.ConfigRecallSize: cast.ToString(r.personalKbRecallBaseCount / 2),
			}
			config.logicConfigMap[stream_chat_default_tab_conf.PersonalKnowledgeBaseRuceneRecallLogic] = map[string]string{
				conf.ConfigRecallSize: cast.ToString(r.personalKbRecallBaseCount),
			}
			config.logicConfigMap[stream_chat_default_tab_conf.KnowledgeBaseInfoLogic] = map[string]string{
				conf.ConfigLimit: "20",
			}
			config.logicConfigMap[stream_chat_default_tab_conf.StreamChatLogic][conf.ChatMessageJsonConfig] = conf.MsgConfig{
				SystemPromptId: "zhida_summary_system_elaborated",
				// config 顺序 决定 msg 的拼接顺序
				MsgConfigArr: []conf.ChatMsgConfig{
					conf.NewChatMsgConfigByKnowledge("zhida_summary_user_kb_v2", conf.PromptByQwenUser, ""),
					conf.NewChatMsgConfigByAssistantResponse("好的，我会参考对话历史和相关的参考内容来回答您的问题。"),
					conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryLimit),
					conf.NewChatMsgConfigByQuery(),
				},
			}.ToJsonString()
		}

		// 如果指定深度思考模式
		if requestCtx.GetBizContext().GetChatStyle() == proto.ChatStyle_DEEP_THINKING {
			userPrompt := "zhida_summary_user_reasoning"
			if len(requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()) > 0 {
				userPrompt = "zhida_summary_user_reasoning_kb"
			}

			//更换为 deepseek-r1 模型
			config.logicConfigMap[stream_chat_default_tab_conf.AgentOverwriteConfigLogic][conf.OverwriteConfigStrategy] = "kb_deep_thinking"
			config.logicConfigMap[stream_chat_default_tab_conf.AgentOverwriteConfigLogic2][conf.OverwriteConfigStrategy] = "kb_deep_thinking"
			config.logicConfigMap[stream_chat_default_tab_conf.StreamChatLogic] = map[string]string{
				conf.JsonConfigLogicKey.ToConvert(): conf.ChatConfig{
					ModelName:    "ds-r1-full-awq-online",
					IsReferences: true,
					MaxTokens:    lo.ToPtr[int32](8192),
					Temperature:  lo.ToPtr[float32](0.7),
					TopP:         lo.ToPtr[float32](0.8),
					Stage:        proto.BusinessStage_GENERATION,
					SecurityConfig: &conf.SecurityConfig{
						SourceId:        rpc.RiskCheckSourceSearchAnswer.ToConvert(),
						ChatMappingType: entities.ChatMappingTypeLLMAnswer.ToConvert(),
						Scene:           proto.ChatType_ZHIDA_PRO_TAB.String(),
					},
				}.ToJsonString(),
				conf.ChatMessageJsonConfig: conf.MsgConfig{
					SystemPromptId:              "zhida_summary_system_reasoning",
					SystemDefaultPromptTemplate: conf.PromptCoderQuery,
					// config 顺序 决定 msg 的拼接顺序
					MsgConfigArr: []conf.ChatMsgConfig{
						conf.NewChatMsgConfigByChatHistory(stream_chat_default_tab_conf.ChatHistoryLimit),
						conf.NewChatMsgConfigByKnowledge(userPrompt, conf.PromptByQwenUser, ""),
					},
				}.ToJsonString(),
				conf.StreamChatIsUseThink: "true",
			}
			reRankConfig := conf.RecallChunkReRankConfig{}
			err := json.Unmarshal([]byte(config.logicConfigMap[stream_chat_default_tab_conf.Recall2ModelChunkAndScoreLogic][conf.JsonConfigLogicKey.ToConvert()]), &reRankConfig)
			if err == nil {
				reRankConfig.TotalSize = 54 * 1024
				config.logicConfigMap[stream_chat_default_tab_conf.Recall2ModelChunkAndScoreLogic][conf.JsonConfigLogicKey.ToConvert()] = util.GetJSONIgnoreError(reRankConfig)
			}
		}

		// 内部文档召回
		if len(requestCtx.GetBizContext().GetAssignmentPersonalKnowledgeBase()) > 0 && requestCtx.GetBizContext().RequestHeader().GetTrafficSource() == proto.TrafficSource_internal_qa {
			config.logicConfigMap[stream_chat_default_tab_conf.InternalKnowledgeBaseRumRecallLogic] = map[string]string{
				conf.ConfigRecallSize: "4",
			}
			config.logicConfigMap[stream_chat_default_tab_conf.InternalKnowledgeBaseRuceneRecallLogic] = map[string]string{
				conf.ConfigRecallSize: "8",
			}
			reRankConfig := conf.RecallChunkReRankConfig{}
			err := json.Unmarshal([]byte(config.logicConfigMap[stream_chat_default_tab_conf.Recall2ModelChunkAndScoreLogic][conf.JsonConfigLogicKey.ToConvert()]), &reRankConfig)
			if err == nil {
				reRankConfig.EachDocHasChunk = true
				reRankConfig.ScoreThreshold = 0.5
				config.logicConfigMap[stream_chat_default_tab_conf.Recall2ModelChunkAndScoreLogic][conf.JsonConfigLogicKey.ToConvert()] = util.GetJSONIgnoreError(reRankConfig)
			}
			messageConfig := conf.MsgConfig{}
			err = json.Unmarshal([]byte(config.logicConfigMap[stream_chat_default_tab_conf.StreamChatLogic][conf.ChatMessageJsonConfig]), &messageConfig)
			if err == nil {
				messageConfig.SystemPromptId = "klara_qa_system"
				messageConfig.ApolloNameSpace = "zhihu.internal-qa-prompts.properties"
				config.logicConfigMap[stream_chat_default_tab_conf.StreamChatLogic][conf.ChatMessageJsonConfig] = util.GetJSONIgnoreError(messageConfig)
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
