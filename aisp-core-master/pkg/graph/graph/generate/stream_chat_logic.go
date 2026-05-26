package generate

import (
	"context"
	"encoding/json"
	"fmt"
	"reflect"
	"regexp"
	"slices"
	"sort"
	"strings"
	"time"

	baselog "git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/prompt"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/generate/stream_chat"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/security"
	graphUtil "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/apollo"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/google/uuid"
	"github.com/imjasonmiller/godice"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// 正则表达式定义已移至 stream_chat/patterns.go

const ThinkingMessage = "正在思考中..."

// StreamChatLogic 流式对话算子
// @logicAuthor: wanghao11
// @logicInfo: 流式对话算子
// @logicConfig: 0 | 聚合的json配置
// @logicConfig: 1 | prompt 组合的顺序
// @logicConfig: 2 | context assistant response
// @logicOutput: 0 | 安全校验结果 bool
// @logicOutput: 1 | stream chat开始的时间戳 int64
// @logicOutput: 2 | 模型返回首token的时间戳 int64
// @logicOutput: 2 | stream chat结束的时间戳 int64
type StreamChatLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	modelGatewayRPC      modelapi.ModelTarget
	klaraEmbeddingClient rpc.KlaraRpcClient
	promptService        prompt.PromptMapperService
	patternRe            *regexp.Regexp
	prefixCacheManager   *stream_chat.PrefixCacheManager
	tracingHelper        *stream_chat.TracingHelper
}

func GetDeepThinkingMessage() string {
	return apollo.GetString(macro.DeepThinkingMessage, ThinkingMessage)
}

func GetRetryMessage() string {
	return apollo.GetString(macro.RetryMessage, ThinkingMessage)
}

const lastToken = "last"

func NewStreamChatLogic(name string, config map[string]string) *StreamChatLogic {
	modelGateway := rpc.DefaultModelGatewayRouter
	res := &StreamChatLogic{
		MergeLogicDecorator:  logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
		modelGatewayRPC:      modelGateway,
		klaraEmbeddingClient: rpcImpl.GetBgeEmbeddingClient("bge-embedding-ai-zhida-online"),
		prefixCacheManager:   stream_chat.NewPrefixCacheManager(modelGateway),
		tracingHelper:        stream_chat.NewTracingHelper(name),
	}
	res.MergeFunc = res.streamChat
	res.promptService = prompt.DefaultPromptMapperService
	return res
}

func (c *StreamChatLogic) getChatConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.ChatConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if configStr == "" {
		log.Errorf(ctx, "StreamChatLogic getChatConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), c.GetName()))
		return conf.ChatConfig{}
	}

	chatConfig := conf.ChatConfig{}
	err := json.Unmarshal([]byte(configStr), &chatConfig)
	if err != nil {
		log.Errorf(ctx, "StreamChatLogic getChatConfig error => config is json unmarshal err")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), c.GetName()))
		return conf.ChatConfig{}
	}

	if chatConfig.Check() != nil {
		log.Errorf(ctx, "StreamChatLogic getChatConfig error => config check err")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_check.%s.count", requestCtx.GetBizContext().Scenes(), c.GetName()))
		return conf.ChatConfig{}
	}

	if chatConfig.ModelName == "" {
		chatConfig.ModelName = entities.Luca80b0127
	}

	if chatConfig.AIProfile == "" {
		chatConfig.AIProfile = "你叫小知，是由知乎研发的大型语言模型。\n你的知识库截止至2022年4月，"
	}

	isDisableReferences := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.StreamChatDisableReferences)
	if isDisableReferences == "true" {
		chatConfig.IsReferences = false
	}

	isCitePage := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.StreamChatIsCitePage)
	chatConfig.IsCitePage = cast.ToBool(isCitePage)

	isUseThink := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.StreamChatIsUseThink)
	chatConfig.IsUseThink = cast.ToBool(isUseThink)

	isThinkSeparated := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.StreamChatIsThinkSeparated)
	chatConfig.IsThinkSeparated = cast.ToBool(isThinkSeparated)
	return chatConfig
}

func (c *StreamChatLogic) getChatMsgConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.MsgConfig {
	configStr := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ChatMessageJsonConfig)
	if configStr == "" {
		log.Errorf(ctx, "StreamChatLogic getChatMsgConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), c.GetName()))
		return conf.MsgConfig{}
	}

	chatMsgConfig := conf.MsgConfig{}
	err := json.Unmarshal([]byte(configStr), &chatMsgConfig)
	if err != nil {
		log.Errorf(ctx, "StreamChatLogic getChatMsgConfig error => config is json unmarshal err")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), c.GetName()))
	}
	return chatMsgConfig
}

func (c *StreamChatLogic) streamChat(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "generate.StreamChatLogic.streamChat")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	// 产品名缓存，在单次请求过程中全局有效
	// 使用 context 级别的缓存，避免并发问题
	productNameCache := make(map[string]bool)
	ctx = context.WithValue(ctx, "productNameCache", productNameCache)

	// 已经出现过的产品ID全局缓存，确保同一个ID只出一次
	usedProductIDsCache := make(map[int64]bool)
	ctx = context.WithValue(ctx, "usedProductIDsCache", usedProductIDsCache)

	startTime := time.Now().UnixMilli()

	chatMsgConfig := c.getChatMsgConfig(ctx, requestCtx)
	chatConfig := c.getChatConfig(ctx, requestCtx)

	var firstTokenTime int64

	baselog.Infof(ctx, "StreamChatLogic streamChat user: %s itemLists: %s", util.GetJSONIgnoreError(user), util.GetJSONIgnoreError(itemLists))

	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "streamChat",
		"logicName": c.GetName(),
		"modelName": chatConfig.ModelName,
	})

	defaultMessage := config.GetString("stream_chat.sec_message", graph_constant.DefaultSecurityRefuseMessage)
	citeSnippets := make([]*entities.CiteSnippet, 0)
	digitalCiteSnippets := make([]*entities.CiteSnippet, 0)
	// 不走模型回答时，返回默认文案
	isDisable := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ChatDisable)
	if cast.ToBool(isDisable) {
		msg := &proto.ChatMessage{
			MessageId:   requestCtx.GetBizContext().RespMessageId(),
			TimestampMs: time.Now().UnixMilli(),
			Type:        proto.ChatMessageType_TEXT,
			Text:        defaultMessage,
		}
		item := entities.ItemFromMessageByAnswerAndType(msg, proto.ChatRespType_UNANSWERABLE)
		requestCtx.GetBizContext().GetChatEvent().GetAnswerProducer().Tracing("Disable 默认回答")
		c.sendItem(requestCtx, item, citeSnippets, digitalCiteSnippets, false, false)
		requestCtx.GetBizContext().GetChatEvent().GetAnswerProducer().Done()
		return []*data_frame.ItemData[entities.Item]{item.IntoFrameItem(requestCtx)}, nil
	}

	// 2025年09月07日14:51:31 新增逻辑
	// 如果items中包含answer 则直接返回
	answerItems := lo.Filter(lo.Flatten(itemLists), func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeLLMAnswer
	})
	if len(answerItems) > 0 {
		if answerItem, isExist := lo.First(answerItems); isExist {
			requestCtx.GetBizContext().GetChatEvent().GetAnswerProducer().Tracing("命中红线必答、Query安全或FAQ回答")
			c.sendItem(requestCtx, answerItem.GetBizItem(), citeSnippets, digitalCiteSnippets, false, false)
			requestCtx.GetBizContext().GetChatEvent().GetAnswerProducer().Done()
			return []*data_frame.ItemData[entities.Item]{answerItem.GetBizItem().IntoFrameItem(requestCtx)}, nil
		}
	}

	aiProfile := chatConfig.AIProfile
	nowTime := time.Now()
	aiProfile += fmt.Sprintf("当前时间是%d年%d月%d日。", nowTime.Year(), nowTime.Month(), nowTime.Day())

	handlerConfigs := make([]conf.ChatMsgConfig, 0)
	handlerConfigs = append(handlerConfigs, conf.NewChatMsgConfigBySystem(chatMsgConfig.SystemPromptId, chatMsgConfig.SystemDefaultPromptTemplate, chatMsgConfig.SystemPromptTag))
	handlerConfigs = append(handlerConfigs, chatMsgConfig.MsgConfigArr...)
	messageHandler := NewMessageHandler(handlerConfigs, requestCtx, lo.Flatten(itemLists), int64(chatConfig.ContextLength), chatConfig.ExtraContextLength, *chatConfig.MaxTokens, false)
	// 处理数据
	// 1. 获取配置中的system信息，处理为system prompt
	systemPrompt, knowledgeBaseCount, systemPromptErr := messageHandler.BuildPromptByDefPrompt(ctx,
		chatMsgConfig.SystemPromptId, chatMsgConfig.SystemDefaultPromptTemplate, chatMsgConfig.SystemPromptTag, chatMsgConfig.ApolloNameSpace)
	if systemPromptErr == nil && systemPrompt != "" {
		aiProfile = systemPrompt
	}

	// 上下文中message
	ctxMessages := lo.Filter(requestCtx.GetBizContext().GetMessages(), func(item *dto.ChatRequestMessage, index int) bool {
		if item == nil {
			return false
		}
		return item.Role != dto.ChatRequestMessageRoleSystem
	})

	// 2. 将items 中清洗出召回内容 整理成知识库 并拼接为message
	// 如果上下文中有指定messages 则直接使用上下文中的messages
	messages := lo.Ternary(len(ctxMessages) > 0, ctxMessages, messageHandler.BuildMessages())

	// 获取原始 query 意图 & 拼接调用安全时的qItem
	var intentionType macro.IntentionType
	var qItem *data_frame.ItemData[entities.Item]
	sourceQueryItems, isOk := requestCtx.GetCommonContext().GetLogicData(conf.SourceQueryItemLogicStoreKey.String()).([]*data_frame.ItemData[entities.Item])
	if isOk && sourceQueryItems != nil && len(sourceQueryItems) > 0 {
		intentionType = sourceQueryItems[0].GetBizItem().GetItemMeta().IntentionType
		// 拼接调用安全时的qItem
		securityMessages := messageHandler.BuildMessagesByConfigArr(lo.Filter(chatMsgConfig.MsgConfigArr, func(item conf.ChatMsgConfig, _ int) bool {
			return item.HandlerType != conf.MsgElementByElementChatHistory
		}))
		securityContent := strings.Join(lo.Map(securityMessages, func(item *dto.ChatRequestMessage, index int) string {
			return item.Content
		}), "\n")
		qItem = entities.ItemWithTextAndType(securityContent, entities.ChatMappingTypeQueryPrompt).IntoFrameItem(requestCtx)
		qItem.GetBizItem().MessageId = requestCtx.GetBizContext().GetCurrentQueryMergeDialogue().Query.MessageId
	}

	req := &dto.ChatRequest{
		ModelName:         chatConfig.ModelName,
		AIProfile:         aiProfile,
		Messages:          messages,
		MaxTokens:         chatConfig.MaxTokens,
		Stop:              chatConfig.Stop,
		Temperature:       chatConfig.Temperature,
		TopP:              chatConfig.TopP,
		PresencePenalty:   chatConfig.PresencePenalty,
		FrequencyPenalty:  chatConfig.FrequencyPenalty,
		TopK:              chatConfig.TopK,
		RepetitionPenalty: chatConfig.RepetitionPenalty,
		EnableThinking:    chatConfig.EnableThinking,
		ThinkingType:      string(chatConfig.ThinkingType),
		ExtraBody:         chatConfig.ExtraBody,
	}

	if chatConfig.UseSystemPromptPrefixCache {
		req = c.prefixCacheManager.BuildRequestWithPrefixCache(ctx, req)
	}

	lastTime := time.Now()

	thinkingMessage := ThinkingMessage
	if chatConfig.IsUseThink {
		thinkingMessage = GetDeepThinkingMessage()
	}
	if requestCtx.GetBizContext().RequestHeader().GetIsRetry() {
		thinkingMessage = GetRetryMessage()
	}

	reqJson := util.GetJSONIgnoreError(req)
	isPass := false
	var lastItem *entities.Item
	if requestCtx.GetBizContext().RequestHeader().Version != graph_constant.ZhiDaV2Version {
		requestCtx.GetBizContext().GetChatEvent().GetAnswerProducer().Tracing(reqJson)
		lastItem = c.genStreamAnswerItem(&dto.ChatResponse{Content: thinkingMessage}, false, false)
		lastItem.ViewKbCount = knowledgeBaseCount
		c.sendItem(requestCtx, lastItem, citeSnippets, digitalCiteSnippets, false, false)
	} else {
		// 需要判断 先触发 think 或 answer 的begin 状态
		if chatConfig.IsUseThink && chatConfig.IsThinkSeparated {
			requestCtx.GetBizContext().GetChatEvent().GetThinkProducer().Tracing(reqJson)
		} else {
			requestCtx.GetBizContext().GetChatEvent().GetAnswerProducer().Tracing(reqJson)
		}
	}

	logger.Infof(ctx, "StreamChat start. req: %+v", req)
	span.LogFields(log.Message("StreamChat start."))

	var resultStream <-chan util.Progress[*dto.ChatResponse]
	if chatConfig.ModelApi == conf.ModelApiResponses {
		resultStream = c.modelGatewayRPC.StreamResponses(ctx, req)
	} else {
		resultStream = c.modelGatewayRPC.StreamChat(ctx, req)
	}

	logger.Infof(ctx, "StreamChat ok.")
	span.LogFields(log.Message("StreamChat ok."))

	// 角标策略
	// v1
	i := 0
	lastContent := ""
	processedContent := ""
	allCiteTimes := make(map[int]int)
	// v2
	// reranker 后的 chunk
	rerankedChunkItems := lo.Filter(lo.Flatten(itemLists), func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
	})

	citeHandler := NewCiteHandler(ctx, rerankedChunkItems, chatConfig.IsReferences && chatConfig.IsCiteV2)
	// 跟踪已经插入的亲自答卡片，确保只插一次
	insertedInPersonCardIds := make(map[int]bool)
	// 待插入的亲自答卡片信息（docIndex -> citeSnippet）
	pendingInPersonCard := make(map[int]*entities.CiteSnippet)
	// 上次处理后的内容，用于检测新的 \n
	lastProcessedContent := ""
	//citationBuffer := ""
	preprocessBuffer := ""
	lastSentence := ""
	citationStart := false

	// Product标记处理相关变量
	//productBuffer := ""
	productStart := false

	lastReasoningContent := ""
	processedReasoningContent := ""

	// 是否允许循环等待安全结果
	isAllowLoop := config.GetBool("stream_chat.sec_is_allow_loop", true)
	if isAllowLoop {
		isAllowLoop = !lo.Contains(config.GetStringArray("stream_chat.sec_un_allow_loops", ",", []string{}),
			requestCtx.GetBizContext().RequestHeader().GetTrafficSource().String())
	}

	// 是否允许首token 先发后审
	isAllowSend := config.GetBool("stream_chat.sec_is_allow_send_first_token", false)
	securityIntervalMs := int64(config.GetInt("stream_chat.security_interval_ms", 300))
	securityIntervalDuration := time.Duration(securityIntervalMs) * time.Millisecond
	var progressV *dto.ChatResponse
	for progress := range resultStream {
		err := progress.E
		if err != nil {
			if err == context.Canceled {
				logger.Infof(ctx, "failed to chat with model gateway. err: %+v", err)
			} else {
				errorItem := c.handleError(ctx, err, requestCtx, chatConfig, req, defaultMessage)
				logger.Errorf(ctx, "failed to chat with model gateway. err: %+v", err)
				if errorItem != nil {
					return []*data_frame.ItemData[entities.Item]{errorItem.IntoFrameItem(requestCtx)}, err
				}
			}
			return nil, err
		}

		progressV = progress.V

		isUseThink := chatConfig.IsUseThink
		isThinkSeparated := chatConfig.IsThinkSeparated
		if progressV.IsEmpty(isUseThink) {
			continue
		}

		if progressV.ReasoningContent != "" && progressV.Content == "" {
			// 对思考内的角标做处理
			curReasoningContent := progressV.ReasoningContent
			deltaContent := c.getDeltaContent(chatConfig, curReasoningContent, lastReasoningContent)
			preprocessBuffer += deltaContent
			// v2 新角标策略
			if stream_chat.PartialCitationPat.MatchString(preprocessBuffer) || stream_chat.ThinkProductPat.MatchString(preprocessBuffer) {
				if stream_chat.PartialCitationPat.MatchString(preprocessBuffer) {
					// 出现 【citaition:x 样式
					citationStart = true
				}
				if stream_chat.ThinkProductPat.MatchString(preprocessBuffer) {
					// 出现 product 样式
					productStart = true
				}
				lastReasoningContent = curReasoningContent
				continue
			} else {
				if citationStart {
					processedBuffer, _ := c.processCitations(ctx, requestCtx, rerankedChunkItems, citeHandler, preprocessBuffer, "", true)
					if productStart {
						// 将 processedReasoningContent 中的 <product> 和 </product> 标签替换成空字符串
						processedBuffer = strings.ReplaceAll(processedBuffer, "<product>", "")
						processedBuffer = strings.ReplaceAll(processedBuffer, "</product>", "")
					}
					processedReasoningContent += processedBuffer
				} else {
					if productStart {
						// 将 processedReasoningContent 中的 <product> 和 </product> 标签替换成空字符串
						preprocessBuffer = strings.ReplaceAll(preprocessBuffer, "<product>", "")
						preprocessBuffer = strings.ReplaceAll(preprocessBuffer, "</product>", "")
						processedReasoningContent += preprocessBuffer
					} else {
						processedReasoningContent += deltaContent
					}
				}
				lastReasoningContent = curReasoningContent
				progressV.ReasoningContent = processedReasoningContent
				preprocessBuffer = ""
				citationStart = false
				productStart = false
			}
		}
		if progressV.Content != "" {

			if processedReasoningContent != "" && progressV.ReasoningContent != "" {
				progressV.ReasoningContent = processedReasoningContent
			}

			curContent := progressV.Content
			// 根据请求，判断是走 2.0 角标还是 1.0 角标
			if chatConfig.IsCiteV2 {

				deltaContent := c.getDeltaContent(chatConfig, curContent, lastContent)
				preprocessBuffer += deltaContent
				lastSentence += deltaContent

				// v2 新角标策略
				if stream_chat.PartialCitationPat.MatchString(preprocessBuffer) || stream_chat.PartialProductPat.MatchString(preprocessBuffer) {
					if stream_chat.PartialCitationPat.MatchString(preprocessBuffer) {
						// 出现 citation 样式
						citationStart = true
					}
					if stream_chat.PartialProductPat.MatchString(preprocessBuffer) {
						// 出现 product 样式
						productStart = true
					}
					lastContent = curContent
					continue

				} else {
					// 没有检测到不完整标签，检查是否有完整的标签需要处理
					if citationStart || productStart {
						// 先添加原始内容（只添加一次）
						processedContent += preprocessBuffer
						if citationStart {
							// 处理 citation 标签
							processedBuffer, newCites := c.processCitations(ctx, requestCtx, rerankedChunkItems, citeHandler, preprocessBuffer, lastSentence, false)

							// 数字角标强调样式
							//digitalLastSentences := strings.Split(lastSentence, "\n")
							//digitalLastSentence := digitalLastSentences[len(digitalLastSentences)-1]
							//lastSentenceWithDigitalStyle, digitalCites := c.processDigitalCitations(ctx, digitalLastSentence, newCites)
							// 先加上数字角标格式
							//processedContent = strings.ReplaceAll(processedContent, digitalLastSentence, lastSentenceWithDigitalStyle)
							// 再将原有的 [citation:1] 更换为 <cite data-id='1'>1</cite> 格式
							processedContent = strings.ReplaceAll(processedContent, preprocessBuffer, processedBuffer)

							citeSnippets = append(citeSnippets, newCites...)
							//digitalCiteSnippets = append(digitalCiteSnippets, digitalCites...)
							//lastSentence = lastSentenceWithDigitalStyle
							lastSentence = ""
							// 检测亲自答卡片，标记待插入（不立即插入，等\n输出后再插入）
							if chatConfig.IsInPersonCiteV2 {
								pendingInPersonCard = c.detectInPersonCard(ctx, newCites, rerankedChunkItems, insertedInPersonCardIds, pendingInPersonCard)
							}
						}
						if productStart {
							// 处理产品标签，返回处理后的标签映射
							//var isTableEnd = false
							// 检查curContent结尾是否为表格结束标记
							/*
								if len(curContent) > 0 {
									content := curContent
									if strings.HasSuffix(content, "|") ||
										strings.HasSuffix(content, "| ") ||
										strings.HasSuffix(content, "| *") ||
										strings.HasSuffix(content, "| **") {
										isTableEnd = true
									}
								}*/
							processedTags := c.processProducts(ctx, preprocessBuffer, false)
							// 对 processedContent 中的原标签格式进行替换
							for originalTag, processedTag := range processedTags {
								processedContent = strings.ReplaceAll(processedContent, originalTag, processedTag)
							}
						}
					} else {
						// 没有标签需要处理，直接添加增量内容
						processedContent += deltaContent
					}
					// 检查是否有新的 \n 出现，如果有且有待插入的亲自答卡片，则在 \n 之后插入
					if chatConfig.IsInPersonCiteV2 && len(pendingInPersonCard) > 0 {
						processedContent, citeSnippets, pendingInPersonCard, insertedInPersonCardIds = c.insertPendingInPersonCard(processedContent, lastProcessedContent, citeSnippets, pendingInPersonCard, insertedInPersonCardIds)
					}
					lastContent = curContent
					lastProcessedContent = processedContent
					progressV.Content = processedContent
					// 清空缓冲区和重置状态
					preprocessBuffer = ""
					citationStart = false
					productStart = false
				}

			} else {
				processedContent += c.progressItemContent(ctx, requestCtx, curContent, lastContent, allCiteTimes)
				lastContent = curContent
				progressV.Content = processedContent
			}
		}
		if i == 0 {
			span.LogFields(log.Message("First Token."), log.OmittedString("content", progressV.GetContent(isUseThink)))
			firstTokenTime = time.Now().UnixMilli()
		}

		// 关闭模型输出过程中日志，只在Debug模式下输出
		if log.GetLevel() == baselog.DebugLevel {
			logger.Debugf(ctx, "StreamChat progressV: %s", util.GetJSONIgnoreError(progressV))
		}

		lastItem = c.genStreamAnswerItem(progressV, isUseThink, isThinkSeparated)
		// 根据意图设置回复类型
		lastItem.ChatRespType = c.genChatRespType(intentionType)
		lastItem.ViewKbCount = knowledgeBaseCount
		// 调用安全接口
		currTime := time.Now()
		if currTime.Sub(lastTime) > securityIntervalDuration && lastItem.Text != thinkingMessage {
			isAllowSend = false
			lastTime = currTime
			item := c.progressItemSec(ctx, requestCtx, cast.ToString(i), qItem, lastItem, chatConfig, intentionType.String())
			if item != nil && item.GetSecurity().IsSecurityAllPassed() {
				lastItem = item
				isAllowSend = true
			}
			if !isAllowSend && !isAllowLoop {
				break
			}
		}

		// 实际 首token 打点
		if i == 0 {
			c.stateDefaultFirstToken(ctx)
		}

		if isAllowSend {
			// 发送到chan
			c.sendItem(requestCtx, lastItem, citeSnippets, digitalCiteSnippets, chatConfig.IsUseThink, chatConfig.IsThinkSeparated)
			c.tracingHelper.SaveTracingMiddleProcess(req, lastItem.Text, progressV, requestCtx)
			isAllowSend = false
		}
		i += 1
	}

	streamChatEndMs := time.Now().UnixMilli()

	// 针对 lastToken 再执行一次，为了打点
	item := c.progressItemSec(ctx, requestCtx, lastToken, qItem, lastItem, chatConfig, intentionType.String())
	if item == nil || item.Text == thinkingMessage || !item.GetSecurity().IsSecurityAllPassed() {
		isPass = false
	} else {
		lastItem = item
		// 发送到chan
		c.sendItem(requestCtx, lastItem, citeSnippets, digitalCiteSnippets, chatConfig.IsUseThink, chatConfig.IsThinkSeparated)
		isPass = true
	}

	if !isPass {
		m := &proto.ChatMessage{
			MessageId:   uuid.New().String(),
			TimestampMs: time.Now().UnixMilli(),
			Type:        proto.ChatMessageType_TEXT,
			Text:        defaultMessage,
		}
		refuseItem := entities.ItemFromMessageByAnswerAndType(m, proto.ChatRespType_REFUSE)
		if lastItem != nil {
			refuseItem.Security = lastItem.Security
		}
		lastItem = refuseItem
		// 发送到chan
		c.sendItem(requestCtx, lastItem, citeSnippets, digitalCiteSnippets, chatConfig.IsUseThink, chatConfig.IsThinkSeparated)
		if progressV != nil {
			macro.ProcessNodeLog.Infof(logCtx, fmt.Sprintf("[安全过滤]%s", progressV.Content))
		}
	}

	// 关闭answer
	requestCtx.GetBizContext().GetChatEvent().GetAnswerProducer().Done()

	logger.Infof(ctx, "StreamChat end loop.")
	span.LogFields(log.Message("StreamChat end loop."))
	resp := make([]*data_frame.ItemData[entities.Item], 0)
	lastItem.MessageId = requestCtx.GetBizContext().RespMessageId()
	resp = append(resp, lastItem.IntoFrameItem(requestCtx))

	c.tracingHelper.SaveTracing(logCtx, req, lastItem.Text, startTime, firstTokenTime, requestCtx)
	c.tracingHelper.SaveTracingMiddleProcess(req, lastItem.Text, progressV, requestCtx)
	c.tracingHelper.SaveAnswerTracing(lastItem.Text, requestCtx, chatConfig.Stage)

	requestCtx.DataMap().SetInt64(logCtx, c.GetOutputName(1), startTime)
	requestCtx.DataMap().SetInt64(logCtx, c.GetOutputName(2), firstTokenTime)
	requestCtx.DataMap().SetInt64(logCtx, c.GetOutputName(3), streamChatEndMs)

	return resp, nil
}

func (c *StreamChatLogic) progressItemContent(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	curContent string, lastContent string, allCiteTimes map[int]int) string {
	chatConfig := c.getChatConfig(ctx, requestCtx)

	curContent = strings.TrimPrefix(curContent, chatConfig.TrimPrefix)
	curContent = strings.TrimSpace(curContent)
	lastContent = strings.TrimPrefix(lastContent, chatConfig.TrimPrefix)
	lastContent = strings.TrimSpace(lastContent)
	appendContent := strings.TrimPrefix(curContent, lastContent)

	if chatConfig.IsReferences {
		curContentLines := strings.Split(curContent, "\n")

		lastSen := ""
		for i, line := range curContentLines {
			if i == len(curContentLines)-1 {
				break
			}

			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}

			lastSen = line
		}

		// 召回结果
		var recallBizItems []*entities.Item
		recallItems, isOk := requestCtx.GetCommonContext().GetLogicData(conf.RecallCardLogicStoreKey.String()).([]*data_frame.ItemData[entities.Item])
		if isOk && recallItems != nil && len(recallItems) > 0 {
			for _, item := range recallItems {
				bizItem := item.GetBizItem()
				if bizItem.IsCitable {
					recallBizItems = append(recallBizItems, bizItem)
					// log.Infof(ctx, "processCite IsCitable. bizItem: %+v", bizItem)
				}
			}
		}

		// 判断单篇还是多篇
		isCitePage := chatConfig.IsCitePage

		pageBizItems := make([]*entities.Item, 0)
		if isCitePage {
			var oneBizItem *entities.Item
			for _, recallBizItem := range recallBizItems {
				oneBizItem = recallBizItem
				break
			}
			if oneBizItem != nil {
				pageBizItems = oneBizItem.GetPageItems(ctx)
			}
		}

		citeTag := "cite"
		citeBizItems := recallBizItems
		if isCitePage && len(pageBizItems) > 0 {
			citeTag = "page"
			citeBizItems = pageBizItems
		}

		senSuffix := config.GetStringArray("stream_chat.cite.sen_suffix", "\n", []string{
			"。",
			"？",
			"?",
			"!",
			"！",
		},
		)
		// 判断是否是句尾
		_, isHit := lo.Find(
			senSuffix,
			func(item string) bool {
				return strings.HasSuffix(lastSen, item)
			})
		_ = isHit

		senMinLength := cast.ToInt(config.GetString("stream_chat.cite.sen_min_length", "10"))

		if strings.Contains(appendContent, "\n") && // 新行
			strings.Count(curContent, "```")%2 == 0 && // 保证代码块闭合
			len(lastSen) > senMinLength && // 策略限制，只有最后一段长度大于10才进行引用
			isHit {

			//log.Infof(ctx, "processCite. lastSen: %s citeBizItems.len: %d", lastSen, len(citeBizItems))
			chooseCiteList := c.processCite(ctx, lastSen, citeBizItems)
			//log.Infof(ctx, "processCite. chooseCiteList.len: %d", len(chooseCiteList))

			localCiteTimes := make(map[int]int)

			siteMarkArray := make([]int, 0)

			for _, chooseCite := range chooseCiteList {
				siteNum := chooseCite.OrderNumber

				maxCount := cast.ToInt(config.GetString("stream_chat.cite.max_count", "5"))
				if chatConfig.CiteMaxCount > 0 {
					maxCount = chatConfig.CiteMaxCount
				}

				if len(siteMarkArray) >= maxCount {
					break
				}

				chunkMaxTimes := cast.ToInt(config.GetString("stream_chat.cite.chunk_max_times", "3"))
				if allCiteTimes[siteNum] >= chunkMaxTimes {
					continue
				}

				if localCiteTimes[siteNum] >= 1 {
					continue
				}

				allCiteTimes[siteNum] += 1
				localCiteTimes[siteNum] += 1

				siteMarkArray = append(siteMarkArray, siteNum)
			}

			sort.IntSlice(siteMarkArray).Sort()
			siteMark := ""
			for _, siteNum := range siteMarkArray {
				siteMark += fmt.Sprintf("<%s>%d</%s>", citeTag, siteNum+1, citeTag)

			}

			siteMark += "\n"
			appendContent = strings.Replace(appendContent, "\n", siteMark, 1)
		}
	}

	return appendContent
}

// 处理模型产出的 citation 标签
func (c *StreamChatLogic) processCitations(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	rerankedChunkItems []*data_frame.ItemData[entities.Item], citeHandler *CiteHandler, citationBuffer, lastSentence string, isThink bool) (string, []*entities.CiteSnippet) {
	// 获取配置
	chatConfig := c.getChatConfig(ctx, requestCtx)
	citeSnippets := make([]*entities.CiteSnippet, 0)
	// 提取 [citation:x] 中的 x
	matches := stream_chat.CitationParser.FindAllStringSubmatch(citationBuffer, -1)
	docIDs := make([]int, 0, len(matches))

	for _, match := range matches {
		if len(match) >= 2 {
			var docID int
			fmt.Sscanf(match[1], "%d", &docID)
			docIDs = append(docIDs, docID)
		}
	}

	// Build citation string

	// 检测前缀类型
	prefix := ""
	suffix := ""
	if strings.Contains(citationBuffer, "([citation:") {
		prefix = "("
		suffix = ")"
	} else if strings.Contains(citationBuffer, "{[citation:") {
		prefix = "{"
		suffix = "}"
	} else if strings.Contains(citationBuffer, "[[citation:") {
		prefix = "["
		suffix = "]"
	}

	var citationStr string
	for _, did := range docIDs {
		citationStr += fmt.Sprintf("%s[citation:%d]%s", prefix, did, suffix)
	}

	if isThink {
		// 思考中的 citation 替换为markdown超链接
		mdHrefCitation := ""
		for _, did := range docIDs {
			if 1 <= did && did <= len(rerankedChunkItems) {
				docIndex := did - 1
				name := fmt.Sprintf("[%d]", did)
				url := rerankedChunkItems[docIndex].GetBizItem().GetItemMeta().Url
				mdHrefCitation += fmt.Sprintf("[%s](%s)", name, url)
			}
		}
		citationBuffer = strings.Replace(citationBuffer, citationStr, "", 1)
	} else {
		// Process last sentence
		parts := strings.Split(lastSentence, citationStr)
		lastSentence = parts[0]

		lines := strings.Split(strings.TrimSpace(lastSentence), "\n")
		lastSentence = lines[len(lines)-1]
		newCitationStr := ""
		if chatConfig.IsReferences {
			for _, docId := range docIDs {
				cite, isExistCite := lo.First(citeHandler.getHighlightCites(ctx, lastSentence, []int{docId}))
				if !isExistCite {
					continue
				}
				if cite.Score < float64(citeHandler.citeRerankThreshold) {
					continue
				}
				newCitationStr += fmt.Sprintf("<cite data-id='%d'>%d</cite>", cite.CiteId, cite.CiteId)
				// 改变下 docidx
				cite.DocIndex = cite.DocIndex - 1
				citeSnippets = append(citeSnippets, cite)
			}
		}
		citationBuffer = strings.Replace(citationBuffer, citationStr, newCitationStr, 1)
	}
	return citationBuffer, citeSnippets
}

// detectInPersonCard 检测亲自答卡片，标记待插入（不立即插入，等\n输出后再插入）
func (c *StreamChatLogic) detectInPersonCard(ctx context.Context, newCites []*entities.CiteSnippet, rerankedChunkItems []*data_frame.ItemData[entities.Item], insertedInPersonCardIds map[int]bool, pendingInPersonCard map[int]*entities.CiteSnippet) map[int]*entities.CiteSnippet {
	// 遍历 newCites，只检查模型使用的doc
	for _, cite := range newCites {
		// 如果已经插入过或已经在待插入列表中，跳过
		if insertedInPersonCardIds[cite.DocIndex] || pendingInPersonCard[cite.DocIndex] != nil {
			continue
		}

		if cite.DocIndex < 0 || cite.DocIndex >= len(rerankedChunkItems) {
			continue
		}

		// 获取对应的 item
		item := rerankedChunkItems[cite.DocIndex]
		if item == nil {
			continue
		}

		// 判断是否是亲自答
		tagInfo := item.GetBizItem().GetItemMeta().TagInfo
		if graphUtil.GetAnswerPropertyTagValue(tagInfo) == rpc.TagCoreAnswerPropertyInPerson {
			// 生成 citeId，使用 docIndex*10000 + 999 作为特殊ID，避免与正常角标冲突
			citeId := cite.DocIndex*10000 + 999

			// 创建 citeSnippet，设置 CiteBizType 为 IN_PERSON
			citeSnippet := &entities.CiteSnippet{
				DocIndex:    cite.DocIndex,
				CiteId:      citeId,
				CiteBizType: proto.CiteBizType_IN_PERSON,
			}
			// 标记为待插入
			pendingInPersonCard[cite.DocIndex] = citeSnippet
			break // 只标记第一个亲自答
		}
	}

	return pendingInPersonCard
}

// insertPendingInPersonCard 检查是否有新的 \n 出现，如果有且有待插入的亲自答卡片，则在 \n 之后插入
// 插入格式：\n<cite data-id='xxx'>xxx</cite>\n
func (c *StreamChatLogic) insertPendingInPersonCard(processedContent string, lastProcessedContent string, citeSnippets []*entities.CiteSnippet, pendingInPersonCard map[int]*entities.CiteSnippet, insertedInPersonCardIds map[int]bool) (string, []*entities.CiteSnippet, map[int]*entities.CiteSnippet, map[int]bool) {
	// 检查是否有新的 \n 出现
	lastNewlineIndex := strings.LastIndex(processedContent, "\n")
	lastLastNewlineIndex := strings.LastIndex(lastProcessedContent, "\n")

	// 如果有新的 \n 出现，且有待插入的亲自答卡片
	if lastNewlineIndex > lastLastNewlineIndex && lastNewlineIndex >= 0 {
		// 找到第一个待插入的亲自答卡片
		for docIndex, citeSnippet := range pendingInPersonCard {
			// 在最后一个 \n 之后插入 cite 标签，然后在 cite 标签末尾再插入一个 \n
			citeTag := fmt.Sprintf("<cite data-id='%d'>%d</cite>\n", citeSnippet.CiteId, citeSnippet.CiteId)
			processedContent = processedContent[:lastNewlineIndex+1] + citeTag + processedContent[lastNewlineIndex+1:]

			// 添加到 citeSnippets
			citeSnippets = append(citeSnippets, citeSnippet)

			// 标记为已插入，确保只插一次
			insertedInPersonCardIds[docIndex] = true

			// 从待插入列表中移除
			delete(pendingInPersonCard, docIndex)
			break // 一个位置只插入第一个
		}
	}

	return processedContent, citeSnippets, pendingInPersonCard, insertedInPersonCardIds
}

// 处理模型产出的 product 标签，复用citation的处理逻辑
// productInfo 产品信息结构
type productInfo struct {
	originalTag    string // 原始标签 <product>name</product>
	originalName   string // 原始名称（保持格式）
	normalizedName string // 标准化名称（去空格、转小写）
}

func (c *StreamChatLogic) processProducts(ctx context.Context, productBuffer string, isTableEnd bool) map[string]string {
	// 1. 提取表格中产品信息，不出id

	var products []productInfo
	processedTags := make(map[string]string)
	//表格中的产品名不出id,只出name:暂时下线
	/*
		TableMatches := TableProductPat.FindAllStringSubmatch(productBuffer, -1)
		for _, match := range TableMatches {
			if len(match) >= 2 {
				originalName := strings.TrimSpace(match[1])
				processedTags[match[0]] = "| " + originalName
			}
		}
	*/
	// 1. 提取非表格中的产品信息,
	matches := stream_chat.ProductParser.FindAllStringSubmatch(productBuffer, -1)
	for i, match := range matches {
		if len(match) < 2 {
			continue
		}

		originalName := strings.TrimSpace(match[1])
		if isTableEnd && i == 0 {
			processedTags[match[0]] = "| " + originalName
			continue
		}

		normalizedName := strings.ToLower(strings.ReplaceAll(originalName, " ", ""))
		products = append(products, productInfo{
			originalTag:    match[0],
			originalName:   originalName,
			normalizedName: normalizedName,
		})
	}

	if len(products) == 0 {
		return make(map[string]string)
	}

	// 2. 获取产品ID映射
	productNameToID := c.getProductIDMapping(ctx, products)

	// 3. 生成替换映射
	for _, product := range products {
		productID := productNameToID[product.normalizedName]
		if productID == 0 {
			// 无有效ID，保留原始名称
			processedTags[product.originalTag] = product.originalName
		} else {
			// 有有效ID，生成产品标签
			processedTags[product.originalTag] = fmt.Sprintf("%s <product data-id='%d'>%d</product>",
				product.originalName, productID, productID)
		}
	}

	return processedTags
}

// getProductIDMapping 获取产品名称到ID的映射
func (c *StreamChatLogic) getProductIDMapping(ctx context.Context, products []productInfo) map[string]int64 {
	// 去重获取唯一的产品名称
	uniqueNames := make(map[string]bool)
	for _, product := range products {
		uniqueNames[product.normalizedName] = true
	}

	productNameToID := make(map[string]int64)
	usedProductIDs := c.getUsedProductIDs(ctx)
	needQueryNames := make([]string, 0)

	// 先检查产品名缓存
	for normalizedName := range uniqueNames {
		if c.isProductNameCached(ctx, normalizedName) {
			// 产品名在缓存中，返回ID为0
			productNameToID[normalizedName] = 0
		} else {
			needQueryNames = append(needQueryNames, normalizedName)
		}
	}

	// 查询接口获取未缓存的产品ID
	if len(needQueryNames) > 0 {
		skuDao := impl.NewZhiDaSkuDao()
		productIDResults := skuDao.GetSkuLinkCardIds(ctx, needQueryNames)

		for normalizedName, productID := range productIDResults {
			if productID == 0 {
				// 无效的产品ID
				productNameToID[normalizedName] = 0
			} else if usedProductIDs[productID] {
				// 该产品ID已经使用过
				productNameToID[normalizedName] = 0
			} else {
				// 有效的产品ID且未使用过
				productNameToID[normalizedName] = productID
				c.markProductIDAsUsed(ctx, productID)
			}
			// 将查询结果更新到产品名缓存
			c.cacheProductName(ctx, normalizedName)
		}
	}

	return productNameToID
}

// 处理数字强调加标
func (c *StreamChatLogic) processDigitalCitations(ctx context.Context, lastSentence string, currentCiteSnippets []*entities.CiteSnippet) (string, []*entities.CiteSnippet) {

	// 1. 识别当前句中的数字单元
	digitalUnits := util.ExtractNumbersWithUnits(lastSentence)

	// 2. 识别角标摘要里的数字单元
	digitalCites := make([]*entities.CiteSnippet, 0)
	for _, digitalUnit := range digitalUnits {
		isMatch := false
		for _, currentCiteSnippet := range currentCiteSnippets {
			// 将 cite.DocAbstract 中的 <highlight> 标签去掉
			docAbstract := strings.ReplaceAll(currentCiteSnippet.DocAbstract, "<highlight>", "")
			docAbstract = strings.ReplaceAll(docAbstract, "</highlight>", "")
			// 识别摘要里的数字单元
			digitalUnitsInCite := util.ExtractNumbersWithUnits(docAbstract)
			for _, digitalUnitInCite := range digitalUnitsInCite {
				if util.AreEquivalentMatches(digitalUnit, digitalUnitInCite) {
					// 匹配到一个数字单位，替换下 last_sentence 为 <cite data-id='1' data-type='digital'>3.20元</cite> 格式
					lastSentence = util.ReplaceOutsideProtectedTags(lastSentence, digitalUnit.OriginalText, fmt.Sprintf("<cite data-id='%d' data-type='digital'>%s</cite>", currentCiteSnippet.CiteId, digitalUnit.OriginalText))
					// 摘要替换为 <highlight> 标签
					docAbstract = util.ReplaceOutsideProtectedTags(docAbstract, digitalUnit.OriginalText, fmt.Sprintf("<highlight>%s</highlight>", digitalUnit.OriginalText))
					// 数字角标
					digitalCites = append(digitalCites, &entities.CiteSnippet{
						DocIndex:    currentCiteSnippet.DocIndex,
						CiteId:      currentCiteSnippet.CiteId,
						DocSentence: lastSentence,
						DocAbstract: docAbstract,
						Rank:        currentCiteSnippet.Rank,
					})
					isMatch = true
					break
				}
			}
			if isMatch {
				break
			}
		}
	}
	return lastSentence, digitalCites
}

// 获取 deltaContent
func (c *StreamChatLogic) getDeltaContent(chatConfig conf.ChatConfig, curContent string, lastContent string) string {
	curContent = strings.TrimPrefix(curContent, chatConfig.TrimPrefix)
	curContent = strings.TrimSpace(curContent)
	lastContent = strings.TrimPrefix(lastContent, chatConfig.TrimPrefix)
	lastContent = strings.TrimSpace(lastContent)
	deltaContent := strings.TrimPrefix(curContent, lastContent)
	return deltaContent
}

func (c *StreamChatLogic) progressItemContentV2(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	curContent string, lastContent string, citeHandler *CiteHandler) (string, []*entities.CiteSnippet) {
	chatConfig := c.getChatConfig(ctx, requestCtx)

	citeSnippets := make([]*entities.CiteSnippet, 0)
	curContent = strings.TrimPrefix(curContent, chatConfig.TrimPrefix)
	curContent = strings.TrimSpace(curContent)
	lastContent = strings.TrimPrefix(lastContent, chatConfig.TrimPrefix)
	lastContent = strings.TrimSpace(lastContent)
	deltaContent := strings.TrimPrefix(curContent, lastContent)

	if !chatConfig.IsReferences {
		return deltaContent, nil
	}

	// 配置了出角标且没有召回 chunk 或者当前在代码区
	if len(citeHandler.candidateCiteSnippets) == 0 || strings.Count(curContent, "```")%2 != 0 {
		return deltaContent, nil
	}

	deltaContentRune := []rune(deltaContent)
	// 获取插入角标的pos
	insertPos := -1
	lastSent := ""
	for idx, c := range deltaContentRune {
		if c == '\n' {
			insertPos = idx
			break
		}
	}
	if insertPos < 0 {
		return deltaContent, nil
	}

	// 找出当前句
	tmpOutput := lastContent + string(deltaContentRune[:insertPos])

	lastSents := strings.Split(strings.TrimSpace(tmpOutput), "\n")
	lastSent = lastSents[len(lastSents)-1]

	isEnglishOnly := citeHandler.isEnglishOnly(lastSent)

	// 当前句不是表格里的一行、不是标题、不是加粗小标题，且字数大于阈值
	if !strings.HasPrefix(strings.TrimSpace(lastSent), "|") &&
		!strings.HasPrefix(strings.TrimSpace(lastSent), "#") &&
		!strings.HasSuffix(strings.TrimSpace(lastSent), "**") &&
		!strings.HasSuffix(strings.TrimSpace(lastSent), "：") &&
		!strings.HasSuffix(strings.TrimSpace(lastSent), ":") &&
		!strings.Contains(strings.TrimSpace(lastSent), `\\`) &&
		!strings.Contains(strings.TrimSpace(lastSent), `$$`) &&
		!strings.Contains(strings.TrimSpace(lastSent), `\[`) &&
		!strings.Contains(strings.TrimSpace(lastSent), `\begin`) &&
		((!isEnglishOnly && util2.CountChineseChars(lastSent) >= citeHandler.minCnSenteceLength) ||
			(isEnglishOnly && len(strings.Split(lastSent, " ")) >= citeHandler.minEnSenteceLength)) {
		selectedCites := citeHandler.getMatchedCites(ctx, lastSent)
		// 插入角标
		if len(selectedCites) > 0 {
			siteMark := ""
			for _, cite := range selectedCites {
				siteMark += fmt.Sprintf("<%s>%d</%s>", graph_constant.CiteTag, cite.CiteId, graph_constant.CiteTag)
				citeSnippets = append(citeSnippets, cite)
			}
			deltaContent = string(deltaContentRune[:insertPos]) + siteMark + string(deltaContentRune[insertPos:])
		}

	}
	return deltaContent, citeSnippets
}

func (c *StreamChatLogic) splitSnippets(content string) []string {
	splitResult := c.patternRe.Split(content, -1)

	highlightOverlap := config.GetInt("stream_chat.cite.highlight_overlap", 5)
	highlightLength := config.GetInt("stream_chat.cite.highlight_length", 40)
	highlightSnippetStep := highlightLength - highlightOverlap

	snippets := make([]string, 0)

	for _, sent := range splitResult {
		sentRune := []rune(sent)
		if len(sentRune) < highlightOverlap {
			continue
		}

		if len(sentRune) < highlightLength {
			snippets = append(snippets, string(sentRune))

			continue
		}

		l := len(sentRune)
		for i := 0; i < l; i += highlightSnippetStep {
			j := min(i+highlightLength, l)
			tmpSent := sentRune[i:j]

			if highlightOverlap <= len(tmpSent) && len(tmpSent) <= highlightLength {
				snippets = append(snippets, string(tmpSent))
			}
		}

	}

	chunkSplitMaxCount := cast.ToInt(config.GetString("stream_chat.cite.chunk_split_max_count", "100"))
	if len(snippets) > chunkSplitMaxCount {
		snippets = snippets[:chunkSplitMaxCount]
	}

	return snippets
}

func (c *StreamChatLogic) processCite(ctx context.Context, sentence string, items []*entities.Item) []*entities.Item {
	senEmbed := c.klaraEmbeddingClient.BatchInferEmbedding(ctx, []string{sentence})
	if len(senEmbed) == 0 {
		return nil
	}

	pattern := config.GetString("stream_chat.cite.split_pattern", "[;；:：。！!？?]+|\n+")
	c.patternRe = regexp.MustCompile(pattern)

	citeMaxItemCount := cast.ToInt(config.GetString("stream_chat.cite.cite_max_item_count", "100"))
	chunkSplitMaxCount := cast.ToInt(config.GetString("stream_chat.cite.chunk_split_max_count", "100"))

	itemWG := safe_group.NewGroupWithTimeout("processCite", 1000).SetLimit(8)
	for i, item := range items {
		if i >= citeMaxItemCount {
			break
		}

		newItem := item

		if newItem.Snippets != nil {
			continue
		}

		itemWG.Go(func() error {
			chunkContent := newItem.Text

			splitResult := c.splitSnippets(chunkContent)

			embeddingRes := c.klaraEmbeddingClient.BatchInferEmbedding(ctx, splitResult)
			if len(embeddingRes) == 0 {
				log.Warnf(ctx, "embeddingRes length not equal to content length")
				return nil
			}

			snippets := make([]*entities.Snippet, 0)

			if len(embeddingRes) == len(splitResult) {
				for i, content := range splitResult {
					snippet := &entities.Snippet{
						Content:   content,
						Embedding: embeddingRes[i],
					}
					snippets = append(snippets, snippet)
				}
			}

			newItem.Snippets = snippets

			return nil
		})
	}
	itemWG.Wait()

	snippetChan := make(chan *entities.Snippet, citeMaxItemCount*chunkSplitMaxCount)
	cosineWG := safe_group.NewGroupWithTimeout("processCite", 1000).SetLimit(8)
	for _, item := range items {
		newItem := item
		cosineWG.Go(func() error {
			snippets := newItem.Snippets
			newItem.CiteMaxScore = 0.0
			for _, snippet := range snippets {
				snippetContent := snippet.Content
				snippetEmbedding := snippet.Embedding

				// 字符距离
				charMatchScore := godice.CompareString(sentence, snippetContent)

				// 余弦相似度
				cosineScore, err := util2.CosineByDefIgnoreNormalize01(senEmbed[0], snippetEmbedding, 0)
				if err != nil {
					log.Warnf(ctx, "CosineByDefIgnoreNormalize error: %v", err)
					cosineScore = 0
				}

				snippet.CharMatchScore = charMatchScore
				snippet.CosineScore = cosineScore

				snippet.Item = newItem

				select {
				case snippetChan <- snippet:
					// 成功发送
				case <-ctx.Done():
					return ctx.Err()
				}
			}

			return nil
		})
	}

	// 等待所有 goroutine 完成后再关闭 channel
	go func() {
		if err := cosineWG.Wait(); err != nil {
			log.Warnf(ctx, "Cosine Chan Wait Err => %v", err)
		}
		close(snippetChan)
	}()

	allSnippets := make([]*entities.Snippet, 0)
	for snippet := range snippetChan {
		allSnippets = append(allSnippets, snippet)
	}

	// 分数归一化
	maxCosineScore := 0.0
	minCharMatchScore := 1.0
	maxCharMatchScore := 0.0
	minCosineScore := 1.0

	for _, snippet := range allSnippets {
		if snippet.CharMatchScore > maxCharMatchScore {
			maxCharMatchScore = snippet.CharMatchScore
		}

		if snippet.CharMatchScore < minCharMatchScore {
			minCharMatchScore = snippet.CharMatchScore
		}

		if snippet.CosineScore > maxCosineScore {
			maxCosineScore = snippet.CosineScore
		}

		if snippet.CosineScore < minCosineScore {
			minCosineScore = snippet.CosineScore
		}
	}

	if maxCharMatchScore >= minCharMatchScore {
		maxCharMatchScore = minCharMatchScore + 0.001
	}

	if maxCosineScore >= minCosineScore {
		maxCosineScore = minCosineScore + 0.001
	}

	cosineScoreWeight := cast.ToFloat64(config.GetString("stream_chat.cite.cosine_score_weight", "1.0"))

	for _, snippet := range allSnippets {
		charMatchScore := snippet.CharMatchScore
		cosineScore := snippet.CosineScore

		if config.GetBool("stream_chat.cite.score_normalization", false) {
			charMatchScore = (charMatchScore - minCharMatchScore) / (maxCharMatchScore - minCharMatchScore)
			cosineScore = (cosineScore - minCosineScore) / (maxCosineScore - minCosineScore)
		}

		score := cosineScoreWeight*cosineScore + (1.0-cosineScoreWeight)*charMatchScore

		snippet.CharMatchScore = charMatchScore
		snippet.CosineScore = cosineScore
		snippet.Score = score
	}

	slices.SortFunc(allSnippets, func(i, j *entities.Snippet) int {
		if i.Score > j.Score {
			return -1
		} else if i.Score < j.Score {
			return 1
		}
		return 0
	})

	scoreThreshold := cast.ToFloat64(config.GetString("stream_chat.cite.cite_score_threshold", "0.75"))

	newItems := make([]*entities.Item, 0)
	for _, snippet := range allSnippets {
		if snippet.Score < scoreThreshold {
			continue
		}

		if snippet.Item == nil {
			continue
		}

		newItems = append(newItems, snippet.Item)

		if snippet.Score > snippet.Item.CiteMaxScore {
			snippet.Item.CiteMaxScore = snippet.Score
		}
	}

	return newItems
}

func (c *StreamChatLogic) genStreamAnswerItem(progressV *dto.ChatResponse, isUseThink bool, isThinkSeparated bool) *entities.Item {
	msgTmp := &proto.ChatMessage{
		MessageId:   uuid.New().String(),
		TimestampMs: time.Now().UnixMilli(),
		Type:        proto.ChatMessageType_TEXT,
		Text:        progressV.Content,
	}
	// 使用思考，且与 summary 合并
	if isUseThink && !isThinkSeparated {
		msgTmp.Text = progressV.GetContent(isUseThink)
	}
	resultItem := entities.ItemFromMessageByAnswer(msgTmp)
	// 使用思考，且与 summary 拆开
	if isUseThink && isThinkSeparated {
		resultItem.Think = strings.TrimSpace(progressV.ReasoningContent)
	}
	return resultItem
}

func (c *StreamChatLogic) sendItem(
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	item *entities.Item,
	citeSnippets []*entities.CiteSnippet, digitalCiteSnippets []*entities.CiteSnippet, isUseThink bool, isThinkSeparated bool) {

	cites := make([]*chat_event.CiteSnippetDto, 0)
	digitalCites := make([]*chat_event.CiteSnippetDto, 0)
	for _, citeObj := range citeSnippets {
		cites = append(cites, citeObj.ToEventCite())
	}
	for _, citeObj := range digitalCiteSnippets {
		digitalCites = append(digitalCites, citeObj.ToEventCite())
	}

	// 当前是think 阶段
	if isUseThink && isThinkSeparated && item.Think != "" {
		thinkProducer := requestCtx.GetBizContext().GetChatEvent().GetThinkProducer()
		if !thinkProducer.IsDone() {
			requestCtx.GetBizContext().GetChatEvent().GetThinkProducer().Send(item.Think)
		}
	}

	if item.Text != "" {
		// 关闭 think producer 由于 底层 once 所以多次关闭无所谓
		if isUseThink && isThinkSeparated {
			requestCtx.GetBizContext().GetChatEvent().GetThinkProducer().Done()
		}
		answer := &chat_event.AnswerContent{
			Content:      item.Text,
			Cites:        cites,
			DigitalCites: digitalCites,
		}
		if item.ChatRespType != proto.ChatRespType_UNKNOWN_RESP {
			answer.ChatRespType = item.ChatRespType
		}
		requestCtx.GetBizContext().GetChatEvent().GetAnswerProducer().Send(answer)
	}
}

func (c *StreamChatLogic) stateDefaultFirstToken(ctx context.Context) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "generate.StreamChatLogic.first_token")
	defer span.Finish()
}

func (c *StreamChatLogic) progressItemSec(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	idx string, qItem *data_frame.ItemData[entities.Item], answerItem *entities.Item, chatConfig conf.ChatConfig, answerType string) *entities.Item {
	if answerItem == nil {
		return nil
	}

	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "generate.StreamChatLogic.progress_"+idx)
	defer span.Finish()
	contentLength := len(answerItem.Think) + len(answerItem.Text)
	span.LogFields(log.Message("StreamChat progress go."),
		log.Int64("contentLength", int64(contentLength)),
	)

	// 调用安全检查
	res := security.CheckItem(ctx, requestCtx,
		[]*data_frame.ItemData[entities.Item]{qItem, answerItem.IntoFrameItem(requestCtx)},
		rpc.RiskCheckSourceId(chatConfig.SecurityConfig.SourceId),
		requestCtx.GetBizContext().GetBizType(),
		entities.ChatMappingType(chatConfig.SecurityConfig.ChatMappingType),
		"", "", false, true, answerType)

	answerItem.GetSecurity().ReviewResult = res

	requestCtx.DataMap().SetBool(logCtx, c.GetOutputName(0), res.IsAvailable)

	if idx == lastToken {
		c.tracingHelper.SaveSecurityTracing(answerItem.GetSecurity(), requestCtx)
	}
	log.StatsdCheckItem(ctx, "StreamChatLogic.progressItem.all", res.IsAvailable)
	log.StatsdCheckItem(ctx, "StreamChatLogic.progressItem."+idx, res.IsAvailable)

	if res.IsAvailable == false {
		span.LogFields(log.Message("StreamChat progress CheckItem break."),
			log.OmittedString("content", answerItem.Text),
			log.Json("res", res),
		)
	}
	return answerItem
}

func (c *StreamChatLogic) genChatRespType(intentionType macro.IntentionType) proto.ChatRespType {
	switch intentionType {
	case macro.GetQueryRouteCompetitor():
		return proto.ChatRespType_PLAIN_TEXT
	default:
		return proto.ChatRespType_UNKNOWN_RESP
	}
}

// getUsedProductIDs 获取全局已使用的产品ID缓存
func (c *StreamChatLogic) getUsedProductIDs(ctx context.Context) map[int64]bool {
	cacheInterface := ctx.Value("usedProductIDsCache")
	if cache, ok := cacheInterface.(map[int64]bool); ok {
		return cache
	}
	return make(map[int64]bool)
}

// markProductIDAsUsed 标记产品ID为已使用
func (c *StreamChatLogic) markProductIDAsUsed(ctx context.Context, productID int64) {
	cacheInterface := ctx.Value("usedProductIDsCache")
	if cache, ok := cacheInterface.(map[int64]bool); ok {
		cache[productID] = true
		log.Debugf(ctx, "Marked product ID as used: %d", productID)
	}
}

// isProductNameCached 检查产品名是否已缓存
func (c *StreamChatLogic) isProductNameCached(ctx context.Context, productName string) bool {
	cacheInterface := ctx.Value("productNameCache")
	if cache, ok := cacheInterface.(map[string]bool); ok {
		return cache[productName]
	}
	return false
}

// cacheProductName 将产品名存入缓存
func (c *StreamChatLogic) cacheProductName(ctx context.Context, productName string) {
	cacheInterface := ctx.Value("productNameCache")
	if cache, ok := cacheInterface.(map[string]bool); ok {
		cache[productName] = true
		log.Debugf(ctx, "Caching product name: %s", productName)
	}
}

func (c *StreamChatLogic) handleError(ctx context.Context, err error, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], chatConfig conf.ChatConfig, chatRequest *dto.ChatRequest, defaultMessage string) *entities.Item {
	// 使用反射访问错误字段
	errValue := reflect.ValueOf(err)
	// 处理指针类型
	if errValue.Kind() == reflect.Ptr {
		if errValue.IsNil() {
			log.Errorf(ctx, "failed to chat with model gateway. err: %+v", err)
			return nil
		}
		errValue = errValue.Elem()
	}

	// 尝试获取 Code 字段
	codeField := errValue.FieldByName("Code")
	if codeField.IsValid() && codeField.Kind() == reflect.String {
		code := codeField.String()
		switch code {
		// 如果是 PreviousResponseNotFound 异常，则删除 prefix cache 缓存，下次重新计算
		case "InvalidParameter.PreviousResponseNotFound":
			log.Errorf(ctx, "Previous response not found. err: %+v", err)
			c.prefixCacheManager.DeletePrefixCache(ctx, chatRequest.ModelName, chatRequest.AIProfile)

		// 如果是命中了模型的安全拦截，则记录安全检查失败
		case "InputTextSensitiveContentDetected":
			item := entities.ItemFromSecurityFailed(defaultMessage, requestCtx.GetBizContext().RespMessageId())
			c.sendItem(requestCtx, item, nil, nil, chatConfig.IsUseThink, chatConfig.IsThinkSeparated)
			log.Errorf(ctx, "Input text sensitive content detected. err: %+v, chatRequest:%s", err, util.GetJSONIgnoreError(chatRequest))
			return item
		}
	}

	return nil
}
