package chat_event

import (
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	aiContent "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/req_macro"
	"github.com/samber/lo"
)

func NewChatEventResponse(sessionId string, respMessageId string) *ChatEventResponse {
	return &ChatEventResponse{
		sessionId:     sessionId,
		respMessageId: respMessageId,
	}
}

type ChatEventResponse struct {
	sessionId     string
	respMessageId string
}

// TransitionContext 用于传递事件转换所需的上下文信息，避免循环引用
type TransitionContext struct {
	IsHitCache bool
}

func (c *ChatEventResponse) Transition(msg *EventInfo, transitionContext *TransitionContext) *proto.ChatResponse {
	return c.TransitionSource(msg, false, transitionContext)
}

func (c *ChatEventResponse) TransitionSource(msg *EventInfo, isEnd bool, transitionContext *TransitionContext) *proto.ChatResponse {
	chatResponse := &proto.ChatResponse{
		State:          lo.Ternary(isEnd, proto.ChatState_COMPLETED, proto.ChatState_PROCESSING),
		ChatStage:      c.stageTransition(msg.GetCurrEventType()),
		ChatStageState: c.stageStateTransition(msg.GetCurrEventState()),
	}

	if transitionContext != nil {
		chatResponse.IsHitCache = transitionContext.IsHitCache
	}

	// 获取各阶段耗时
	chatDurationMap := make(map[string]int64)
	for k, v := range msg.GetDurationMap() {
		chatDurationMap[c.stageTransition(k).String()] = v
	}
	chatResponse.ProcessingDuration = chatDurationMap

	for _, eventType := range msg.GetHistoryEventType() {
		switch eventType {
		case RetrievalEventType:
			retrievalResponses := make([]*proto.RetrievalResponse, 0)
			for _, retrievalEventInfo := range msg.GetRetrieval() {
				// 如果存在 eventBus 的耗时则表示 当前轮执行完毕
				_, isExistDuration := retrievalEventInfo.getSourceDurationMap()[eventBus]
				retrievalEventInfo.GetHistoryEventType()
				retrievalResponse := &proto.RetrievalResponse{
					ChatStage:      c.stageTransition(retrievalEventInfo.GetCurrEventType()),
					ChatStageState: c.stageStateTransition(retrievalEventInfo.GetCurrEventState()),
					RetrievalState: lo.Ternary(isExistDuration, proto.ChatStageState_CSS_END, proto.ChatStageState_CSS_PROCESSING),
				}

				for _, et := range retrievalEventInfo.GetHistoryEventType() {
					switch et {
					case TopicEventType:
						if retrievalEventInfo.GetTopic() != nil {
							topicContent := retrievalEventInfo.GetTopic()
							informationSourceList := make([]proto.KnowledgeBaseType, 0)
							referenceMounts := make([]*proto.ReferenceMount, 0)
							for _, sourceInfo := range topicContent.SourceInfos {
								switch sourceInfo.Type {
								case req_macro.SourceTypeIndex:
									if informationSource, isExist := enums.KnowledgeBaseNameTypeMap[sourceInfo.Meta.Name]; isExist {
										informationSourceList = append(informationSourceList, informationSource)
									}
								case req_macro.SourceTypeKnowledgeBase:
									if sourceInfo.Meta.KnowledgeBaseType != proto.PersonalKnowledgeBaseType_PKB_UNDEFINED {
										referenceMounts = append(referenceMounts, &proto.ReferenceMount{
											MountBase: &proto.PersonalKnowledgeBase{
												KnowledgeBaseId:   sourceInfo.Meta.ID,
												KnowledgeBaseType: sourceInfo.Meta.KnowledgeBaseType,
												KnowledgeBaseName: sourceInfo.Meta.Name,
											},
										})
									}
								case req_macro.SourceTypePortfolio:
									if sourceInfo.Meta.ID != 0 && sourceInfo.Meta.DocType == aiContent.DocType_Member {
										referenceMounts = append(referenceMounts, &proto.ReferenceMount{
											MountDoc: &proto.DocIdentity{
												DocId:   sourceInfo.Meta.ID,
												DocType: proto.DocType_MEMBER,
												DocName: sourceInfo.Meta.Name,
											},
										})
									}
								case req_macro.SourceTypeSelected:
									if sourceInfo.Meta.ID != 0 {
										referenceMounts = append(referenceMounts, &proto.ReferenceMount{
											MountDoc: &proto.DocIdentity{
												DocId:   sourceInfo.Meta.ID,
												DocType: model.GetZhiDaDocType(sourceInfo.Meta.DocType),
												DocName: sourceInfo.Meta.Name,
											},
										})
									}
								}
							}

							retrievalResponse.RetrievalTopic = topicContent.Topic
							retrievalResponse.RetrievalType = c.rtTransition(topicContent.RetrievalType)
							retrievalResponse.CurrReferenceMount = referenceMounts
							retrievalResponse.KnowledgeBases = informationSourceList
						}
					case KeywordsEventType:
						retrievalResponse.RetrievalKeywords = retrievalEventInfo.GetKeywords()
					case ReferenceEventType:
						retrievalRefs := make([]*proto.ChatCardProRelevantSource, 0)
						retrievalReferences := retrievalEventInfo.GetReferences()
						for _, card := range retrievalReferences {
							switch x := card.GetCardContent().(type) {
							case *proto.ChatCard_ZhidaRelevantSource:
								retrievalRefs = append(retrievalRefs, x.ZhidaRelevantSource)
							default:
							}
						}
						retrievalResponse.Refs = retrievalRefs
					case AnswerEventType:
						if retrievalEventInfo.GetAnswerContent() != nil {
							retrievalResponse.RespType = retrievalEventInfo.GetAnswerContent().ChatRespType
							retrievalResponse.Summary = retrievalEventInfo.GetAnswerContent().Content
						}
					}
				}
				retrievalResponses = append(retrievalResponses, retrievalResponse)
			}
			chatResponse.RetrievalResponse = retrievalResponses
		case KeywordsEventType:
			chatResponse.RetrievalKeywords = msg.GetKeywords()
		case ReferenceEventType:
			chatResponse.Cards = msg.GetReferences()
		case ThinkEventType:
			chatResponse.RespType = proto.ChatRespType_PLAIN_TEXT
			chatResponse.Think = msg.GetThinkContent()
		case AnswerEventType:
			answerContent := ""
			if msg.GetAnswerContent() != nil {
				answerContent = msg.GetAnswerContent().Content
				chatResponse.RespType = msg.GetAnswerContent().GetChatRespType()
				chatResponse.CiteDict = msg.GetAnswerContent().GetCiteMap()
				chatResponse.DigitalCiteDict = msg.GetAnswerContent().GetDigitalCiteMap()
			}

			chatResponse.Message = &proto.ChatMessage{
				MessageId:   c.respMessageId,
				TimestampMs: time.Now().UnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        answerContent,
			}
		case RelateQueriesEventType:
			queries := make([]*proto.Query, 0)
			for _, q := range msg.GetRelateQueries() {
				queries = append(queries, &proto.Query{
					Id:        q.QueryID,
					Query:     q.QueryText,
					QueryType: q.QueryType,
					RiskType:  q.RiskType,
				})
			}
			chatResponse.RelevantQueries = queries
		}
	}
	return chatResponse
}

func (c *ChatEventResponse) stageTransition(eventType ChatEventType) proto.ChatStage {
	switch eventType {
	case KeywordsEventType:
		return proto.ChatStage_STAGE_KEYWORDS
	case ReferenceEventType:
		return proto.ChatStage_STAGE_REFERENCE
	case ThinkEventType:
		return proto.ChatStage_STAGE_THINK
	case AnswerEventType:
		return proto.ChatStage_STAGE_ANSWER
	default:
		return proto.ChatStage_STAGE_RETRIEVAL
	}
}

func (c *ChatEventResponse) rtTransition(rt RetrievalType) proto.RetrievalType {
	switch rt {
	case RtBrowse:
		return proto.RetrievalType_RT_BROWSE
	case RtSearch:
		return proto.RetrievalType_RT_SEARCH
	case RtSelect:
		return proto.RetrievalType_RT_SELECT
	default:
		return proto.RetrievalType_RT_UNDEFINED
	}
}

func (c *ChatEventResponse) stageStateTransition(state ChatEventState) proto.ChatStageState {
	switch state {
	case StateBegin:
		return proto.ChatStageState_CSS_BEGIN
	case StateProcessing:
		return proto.ChatStageState_CSS_PROCESSING
	case StateEnd:
		return proto.ChatStageState_CSS_END
	default:
		return proto.ChatStageState_CSS_UNKNOWN
	}
}
