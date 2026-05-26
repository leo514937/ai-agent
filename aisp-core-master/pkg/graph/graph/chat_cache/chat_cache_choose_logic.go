package chat_cache

import (
	"context"
	"fmt"
	"regexp"
	"text/template"
	"time"

	apollo "git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	word_service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	graphUtil "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// 直答站内流量来源
var zhidaInnerTrafficSource = []proto.TrafficSource{proto.TrafficSource_undefined_traffic, proto.TrafficSource_zhida}
var statsPrefix = macro.CommonStatsPrefix + ".cache.%s.count"

// URL
var urlPattern = regexp.MustCompile(`^(https?://)?(www\.)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/.*)?$`)

// ChatCacheChooseLogic 词选择算子
// @logicAuthor: zhoupengcheng
// @logicInfo: 引导词结果缓存获取
// @logicOutput: 0 | hitResponseCache bool
type ChatCacheChooseLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	wordService   word_service.WordMapperService
	redisDao      dao.QueryResultDao
	statsTemplate *template.Template
}

func NewChatCacheChooseLogic(name string, config map[string]string) *ChatCacheChooseLogic {
	res := &ChatCacheChooseLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.wordService = word_service.NewWordMapperService()
	res.redisDao = impl.DefaultQueryResultDaoImpl
	res.MergeFunc = res.realMerge
	// 选择条件边
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (q *ChatCacheChooseLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	logOp := "ChatCacheChooseLogic.chooseKey"
	span, ctx, _ := log.StartChildSpanWithContext(ctx, logOp)
	defer span.Finish()
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": logOp,
	})

	hitCache := param.RequestContext.GetBizContext().GetHitCacheResp() != nil
	logger.Infof(ctx, "Chat is hit cache: %v", hitCache)

	// 记录 tracing
	param.RequestContext.GetBizContext().Tracing().ProcessTracing.IsHitCache = hitCache
	resEdge := entities.MissCache
	if hitCache {
		resEdge = entities.HitCache
	}

	// 打点
	util.Increment(ctx, statsPrefix, resEdge)
	return resEdge
}

func (q *ChatCacheChooseLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "ChatCacheChooseLogic.HitCache")
	defer span.Finish()

	logger := log.WithField(ctx, "func", "ChatCacheChooseLogic.HitCache")
	logger.Debug(ctx, "do running...")

	// 多路召回 扁平化处理
	items := lo.Flatten(itemLists)
	query := requestCtx.GetBizContext().RequestMessage().GetText()
	cacheTTl, _ := requestCtx.GetBizContext().GetChatCacheSecTTLByTrafficSource()
	hitCache := false
	// 1. 如果启用缓存 且 当前用户没有有对话历史 则满足初步条件
	// 启用缓存 && 对话历史为空 && 不是重答场景 && 通过词的前置验证 && 非关闭缓存用户
	noCacheMemberIds := apollo.GetStringArray(macro.NoCacheMemberIds, ",", []string{})
	if requestCtx.GetBizContext().IsEnableCache() &&
		len(requestCtx.GetBizContext().GetRealHistoryDialogue()) == 0 &&
		cacheTTl >= 0 &&
		requestCtx.GetBizContext().GetChatSchema() != enums.ChatSchemaByReAnswer &&
		q.wordService.IsWordByBefore(query) &&
		!util.StringInSlice(util.Int64String(requestCtx.GetBizContext().MemberId()), noCacheMemberIds) {

		flag := true
		// 如果是 直答流量来源 还需要单独验证 会话轮数
		if requestCtx.GetBizContext().RequestHeader() != nil &&
			lo.Contains(zhidaInnerTrafficSource, requestCtx.GetBizContext().RequestHeader().GetTrafficSource()) {
			flag = len(requestCtx.GetBizContext().GetRealHistoryDialogue()) == 0
		}
		if flag {
			chatModel := requestCtx.GetBizContext().GetCustomChatModel().String()
			clientSource := requestCtx.GetBizContext().RequestHeader().GetClientSource().String()
			trafficSource := requestCtx.GetBizContext().RequestHeader().GetTrafficSource().String()

			cacheQuery := query
			// 2024-09-23 14:49:15
			// 如果是实体词场景 缓存为 query:docId:docType:matchOrder
			chatExtraInfo := requestCtx.GetBizContext().GetChatExtraInfo()
			sourceContent := chatExtraInfo.GetSourceContent()
			if lo.Contains(graphUtil.GetEntityTrafficSources(), requestCtx.GetBizContext().RequestHeader().GetTrafficSource()) &&
				sourceContent != nil && sourceContent.GetDocId() > 0 {
				cacheQuery = fmt.Sprintf("%s:%d:%s:%d", query, sourceContent.GetDocId(), sourceContent.GetDocType().String(), chatExtraInfo.GetMatchOrder())
			}

			// 2. 查询当前Query 是否命中缓存
			abMap := requestCtx.GetBizContext().GetAbParamAllValueWithoutDefaultFlattened()
			cache, err := q.redisDao.GetResponseInfo(ctx, requestCtx.GetBizContext().Scenes(), clientSource, trafficSource, chatModel, abMap, cacheQuery)

			if err == nil && cache != nil {
				// 1. 处理 Retrieval
				if _, isExist := cache.ProcessingDuration[proto.ChatStage_STAGE_RETRIEVAL.String()]; isExist && len(cache.GetRetrievalResponse()) > 0 {
					retrievalEventProducer := requestCtx.GetBizContext().GetChatEvent().GetRetrievalEventProducer()
					for _, child := range cache.GetRetrievalResponse() {
						retrievalType := chat_event.RtUndefined
						switch child.GetRetrievalType() {
						case proto.RetrievalType_RT_BROWSE:
							retrievalType = chat_event.RtBrowse
						case proto.RetrievalType_RT_SEARCH:
							retrievalType = chat_event.RtSearch
						case proto.RetrievalType_RT_SELECT:
							retrievalType = chat_event.RtSelect
						}

						retrievalChildProducer := retrievalEventProducer.GetOrCreateRoundRetrievalProducer()

						// 发送Topic
						retrievalChildProducer.GetTopicProducer().Send(&chat_event.TopicContent{
							Topic:         child.GetRetrievalTopic(),
							RetrievalType: retrievalType,
						}).Done()
						// 随机睡眠
						util.RandomSleep(10, 50)

						// 发送Keywords
						retrievalChildProducer.GetKeywordsProducer().Send(child.GetRetrievalKeywords()).Done()
						// 随机睡眠
						util.RandomSleep(10, 50)

						// 发送Refs
						referenceChildProducer := retrievalChildProducer.GetReferenceProducer()
						util.RandomSleep(10, 50)
						retrievalCards := make([]*proto.ChatCard, 0)
						for _, refCard := range child.GetRefs() {
							retrievalCards = append(retrievalCards, &proto.ChatCard{
								CardContent: &proto.ChatCard_ZhidaRelevantSource{
									ZhidaRelevantSource: refCard,
								},
							})
						}
						referenceChildProducer.Send(retrievalCards).Done()
						util.RandomSleep(1, 10)

						// 发送Summary
						answerChildProducer := retrievalChildProducer.GetAnswerProducer()
						util.RandomSleep(10, 80)
						answerChildProducer.Send(&chat_event.AnswerContent{
							Content: child.GetSummary(),
						}).Done()
						// 随机睡眠
						util.RandomSleep(1, 10)
						retrievalChildProducer.ProducerDone()
					}
					retrievalEventProducer.Done()
				}

				logger.Infof(ctx, "get response info success: %v cache: %v", err, cache)
				items = make([]*data_frame.ItemData[entities.Item], 0)

				// 2. 处理Keywords(如果命中了 Retrieval，则改阶段自动失效)
				if _, isExist := cache.ProcessingDuration[proto.ChatStage_STAGE_KEYWORDS.String()]; isExist && len(cache.GetRetrievalKeywords()) > 0 {
					requestCtx.GetBizContext().GetChatEvent().GetKeywordsProducer().Send(cache.GetRetrievalKeywords()).Done()
				}

				// 3. 处理Refs(如果命中了 Retrieval，则改阶段自动失效)
				if _, isExist := cache.ProcessingDuration[proto.ChatStage_STAGE_REFERENCE.String()]; isExist && len(cache.GetCards()) > 0 {
					requestCtx.GetBizContext().GetChatEvent().GetReferenceProducer().Send(cache.GetCards()).Done()
				}

				// 4. 处理Think
				if _, isExist := cache.ProcessingDuration[proto.ChatStage_STAGE_THINK.String()]; isExist {
					thinkProducer := requestCtx.GetBizContext().GetChatEvent().GetThinkProducer()
					util.RandomSleep(10, 50)
					thinkProducer.Send(cache.GetThink()).Done()
				}

				// 5. 处理Answer
				if _, isExist := cache.ProcessingDuration[proto.ChatStage_STAGE_ANSWER.String()]; isExist {
					answerProducer := requestCtx.GetBizContext().GetChatEvent().GetAnswerProducer()
					util.RandomSleep(10, 50)

					// 处理cites
					cites := make([]*chat_event.CiteSnippetDto, 0)
					digitalCites := make([]*chat_event.CiteSnippetDto, 0)
					for citeId, cd := range cache.GetCiteDict() {
						cites = append(cites, &chat_event.CiteSnippetDto{
							DocIndex:    int(cd.GetCardIdx()),
							CiteId:      int(citeId),
							DocAbstract: cd.GetSnippet(),
							CiteBizType: cd.GetBizType(),
							// TODO zpc 将来热点还需要增加
							//cd.GetImageUrl(),
							//cd.GetImageToken(),
							//cd.GetVideoId(),
						})
					}
					for citeId, cd := range cache.GetDigitalCiteDict() {
						digitalCites = append(digitalCites, &chat_event.CiteSnippetDto{
							DocIndex:    int(cd.GetCardIdx()),
							CiteId:      int(citeId),
							DocAbstract: cd.GetSnippet(),
							CiteBizType: cd.GetBizType(),
							// TODO zpc 将来热点还需要增加
							//cd.GetImageUrl(),
							//cd.GetImageToken(),
							//cd.GetVideoId(),
						})
					}

					// 设置当前对话Answer
					dialogMessage := q.handleDialogMessage(requestCtx, cache.GetMessage())
					items = append(items, dialogMessage)
					answerProducer.Send(&chat_event.AnswerContent{
						Content:      cache.GetMessage().GetText(),
						ChatRespType: cache.GetRespType(),
						Cites:        cites,
						DigitalCites: digitalCites,
					}).Done()
				}

				cacheFromRespMessageId := cache.GetMessage().GetMessageId()

				hitCache = true
				// 设置状态为命中缓存
				requestCtx.GetBizContext().SetHitCacheResp(cache)
				requestCtx.GetBizContext().Tracing().HitCacheRespMessageId = cacheFromRespMessageId

				constant.DataInputNodeLog.Infof(logCtx, "%s", query)
				macro.ProcessNodeLog.Infof(logCtx, "hit cache! cache from response message id : %s", cacheFromRespMessageId)
				constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(cache))

				requestCtx.DataMap().SetBool(logCtx, q.GetOutputName(0), hitCache)
				return items, nil
			}
		}
	}

	requestCtx.DataMap().SetBool(logCtx, q.GetOutputName(0), hitCache)
	macro.ProcessNodeLog.Infof(logCtx, "did not hit cache")

	return items, nil
}

// handleDialogMessage 处理对话消息
func (q *ChatCacheChooseLogic) handleDialogMessage(
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	message *proto.ChatMessage) *data_frame.ItemData[entities.Item] {
	if message == nil {
		return nil
	}

	// 生成 Answer 并保存到上下文
	answerDialog := entities.NewAnswerDialogFormProtoChatRequest(
		requestCtx.GetBizContext(), message.GetText(), model.DialogCreateTypeLLM, model.DialogErrorTypeNormal)
	requestCtx.GetBizContext().SetCurrentDialogueByAnswer(answerDialog)

	// 生成新的 chatMessage
	msgTmp := &proto.ChatMessage{
		MessageId:   answerDialog.MessageId,
		TimestampMs: time.Now().UnixMilli(),
		Type:        proto.ChatMessageType_TEXT,
		Text:        message.GetText(),
	}
	answerItem := entities.ItemFromMessageByAnswer(msgTmp)
	return answerItem.IntoFrameItem(requestCtx)
}
