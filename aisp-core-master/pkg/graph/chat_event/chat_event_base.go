package chat_event

import (
	"sync"
	"sync/atomic"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/req_macro"
	"github.com/google/uuid"
	"github.com/samber/lo"
)

const (
	traceEventType         ChatEventType = -4
	RouterEventType        ChatEventType = -3
	TopicEventType         ChatEventType = -2
	RelateQueriesEventType ChatEventType = -1
	// ---------  ChatEventType < 0 则不计入状态管控
	unknown            ChatEventType = 0
	eventBus           ChatEventType = 1
	RetrievalEventType ChatEventType = 2
	KeywordsEventType  ChatEventType = 3
	ReferenceEventType ChatEventType = 4
	ThinkEventType     ChatEventType = 5
	AnswerEventType    ChatEventType = 6
)

type ChatEventType int

func (c ChatEventType) String() string {
	switch c {
	case eventBus:
		return "EventBus"
	case RetrievalEventType:
		return "RetrievalEventType"
	case KeywordsEventType:
		return "KeywordsEventType"
	case ReferenceEventType:
		return "ReferenceEventType"
	case ThinkEventType:
		return "ThinkEventType"
	case AnswerEventType:
		return "AnswerEventType"
	case RelateQueriesEventType:
		return "RelateQueriesEventType"
	case TopicEventType:
		return "TopicEventType"
	case traceEventType:
		return "TraceEventType"
	case RouterEventType:
		return "RouterEventType"
	default:
		return "UnknownEventType"
	}
}

const (
	StateUnknown    ChatEventState = 0
	StateBegin      ChatEventState = 1
	StateProcessing ChatEventState = 2
	StateEnd        ChatEventState = 3
)

type RetrievalType int

const (
	RtUndefined RetrievalType = 0
	RtSearch    RetrievalType = 1
	RtBrowse    RetrievalType = 2
	RtSelect    RetrievalType = 3
)

func (c RetrievalType) String() string {
	switch c {
	case RtSearch:
		return "Search"
	case RtBrowse:
		return "Browse"
	case RtSelect:
		return "Select"
	default:
		return "Undefined"
	}
}

type ChatEventState int

func (c ChatEventState) String() string {
	switch c {
	case StateBegin:
		return "StateBegin"
	case StateProcessing:
		return "StateProcessing"
	case StateEnd:
		return "StateEnd"
	default:
		return "StateUnknown"
	}
}

type CiteSnippet struct {
	DocIndex    int       // 参考来源里 doc 的索引
	CiteId      int       // 角标 id
	DocSentence string    // 文章中的句子
	DocAbstract string    // 摘要
	Embedding   []float32 // 句子的嵌入信息
	Score       float64   // 角标得分
	Rank        int       // 排序, 0 普通, 1 c4+答主, 2 白名单答主
}

type CiteSnippetDto struct {
	DocIndex    int               // 参考来源里 doc 的索引
	CiteId      int               // 角标 id
	DocSentence string            // 文章中的句子
	DocAbstract string            // 摘要
	Score       float64           // 角标得分
	CiteBizType proto.CiteBizType // 角标业务类型
}

type AnswerContent struct {
	Content      string
	ChatRespType proto.ChatRespType
	Cites        []*CiteSnippetDto // 普通角标
	DigitalCites []*CiteSnippetDto // 数字角标
}

func (c *AnswerContent) GetChatRespType() proto.ChatRespType {
	if proto.ChatRespType_UNKNOWN_RESP == c.ChatRespType {
		return proto.ChatRespType_PLAIN_TEXT
	}
	return c.ChatRespType
}

func (c *AnswerContent) GetCiteMap() map[int32]*proto.CiteDict {
	citeDict := lo.SliceToMap(c.Cites, func(item *CiteSnippetDto) (int32, *proto.CiteDict) {
		return int32(item.CiteId), &proto.CiteDict{
			CardIdx: int32(item.DocIndex),
			Snippet: item.DocAbstract,
			BizType: item.CiteBizType,
		}
	})
	return citeDict
}
func (c *AnswerContent) GetDigitalCiteMap() map[int32]*proto.CiteDict {
	citeDict := lo.SliceToMap(c.DigitalCites, func(item *CiteSnippetDto) (int32, *proto.CiteDict) {
		return int32(item.CiteId), &proto.CiteDict{
			CardIdx: int32(item.DocIndex),
			Snippet: item.DocAbstract,
		}
	})
	return citeDict
}

type TopicContent struct {
	Topic         string
	RetrievalType RetrievalType
	SourceInfos   []*req_macro.SourceInfo
}

type RelateQueries struct {
	QueryID   string
	QueryText string
	QueryType proto.QueryType
	RiskType  string
}

type chatEventMsg struct {
	chatEventChildBase
	traceFromEventType ChatEventType
	data               any
}

func (c *chatEventMsg) GetTraceFromEventType() ChatEventType {
	return c.traceFromEventType
}

type chatEventChildBase struct {
	parentProducerID string
	producerID       string
	dataPackageID    string
	eventType        ChatEventType
	stage            ChatEventState
	isDone           bool
}

func (cc *chatEventChildBase) GetProducerID() string {
	return cc.producerID
}

func (cc *chatEventChildBase) GetParentProducerID() string {
	return cc.parentProducerID
}

func (cc *chatEventChildBase) GetDataPackageID() string {
	return cc.dataPackageID
}

func (cc *chatEventChildBase) GetEventType() ChatEventType {
	return cc.eventType
}

func (cc *chatEventChildBase) GetStage() ChatEventState {
	return cc.stage
}

func (cc *chatEventChildBase) IsDone() bool {
	return cc.isDone
}

type eventMeta struct {
	parentProducerID string
	producerID       string
	eventType        ChatEventType
}

func (cc *eventMeta) GetProducerID() string {
	return cc.producerID
}

func (cc *eventMeta) GetParentProducerID() string {
	return cc.parentProducerID
}

func (cc *eventMeta) GetEventType() ChatEventType {
	return cc.eventType
}

type EventProducerBase interface {
	GetEventType() ChatEventType
	GetParentProducerID() string
	GetProducerID() string
}

type EventProducer[T any] interface {
	EventProducerBase
	Send(data T) EventProducer[T]
	Tracing(trace string) EventProducer[T]
	IsDone() bool
	Done()
}

type GenericEventProducer[T any] struct {
	chatEventChildBase
	chatEvent        *ChatEvent
	isDone           atomic.Bool
	producerDoneOnce sync.Once
	eventType        ChatEventType
}

// NewGenericEventProducer 创建泛型事件生产者
func newGenericEventProducer[T any](chatEvent *ChatEvent, dataPackageId string, parentProducerId string, eventType ChatEventType) *GenericEventProducer[T] {
	producer := &GenericEventProducer[T]{
		chatEvent: chatEvent,
		eventType: eventType,
	}
	producer.dataPackageID = dataPackageId
	producer.parentProducerID = parentProducerId
	producer.producerID = uuid.NewString()
	producer.chatEventChildBase.eventType = eventType

	// 发起开始事件
	producer.chatEvent.beginBySource(producer.GetDataPackageID(), producer.GetParentProducerID(), producer.GetProducerID(), producer.GetEventType())
	return producer
}

// Tracing 记录Tracing
func (g *GenericEventProducer[T]) Tracing(trace string) EventProducer[T] {
	if g.chatEvent == nil || g.chatEvent.IsProducerDone() || g.isDone.Load() {
		return g
	}

	eventMsg := &chatEventMsg{}
	eventMsg.dataPackageID = g.GetDataPackageID()
	eventMsg.parentProducerID = g.GetParentProducerID()
	eventMsg.producerID = g.GetProducerID()
	eventMsg.traceFromEventType = g.GetEventType()
	eventMsg.eventType = traceEventType
	eventMsg.data = trace
	g.chatEvent.sendEvent(eventMsg)
	return g
}

// Send 发送数据
func (g *GenericEventProducer[T]) Send(data T) EventProducer[T] {
	if g.chatEvent == nil || g.chatEvent.IsProducerDone() || g.isDone.Load() {
		return g
	}

	eventMsg := &chatEventMsg{}
	eventMsg.dataPackageID = g.GetDataPackageID()
	eventMsg.parentProducerID = g.GetParentProducerID()
	eventMsg.producerID = g.GetProducerID()
	eventMsg.eventType = g.GetEventType()
	eventMsg.stage = StateProcessing
	eventMsg.data = data
	g.chatEvent.sendEvent(eventMsg)
	return g
}

// Done 完成生产者
func (g *GenericEventProducer[T]) Done() {
	g.producerDoneOnce.Do(func() {
		if g.chatEvent == nil || g.chatEvent.IsProducerDone() || g.isDone.Load() {
			return
		}
		g.chatEvent.endBySource(g.GetDataPackageID(), g.GetParentProducerID(), g.GetProducerID(), g.GetEventType())
		g.isDone.Store(true)
	})
}

// IsDone 判断是否完成
func (g *GenericEventProducer[T]) IsDone() bool {
	return g.isDone.Load()
}

// GetEventType 获取事件类型
func (g *GenericEventProducer[T]) GetEventType() ChatEventType {
	return g.eventType
}

type KeywordsEventProducer = GenericEventProducer[[]string]
type ThinkEventProducer = GenericEventProducer[string]
type AnswerEventProducer = GenericEventProducer[*AnswerContent]
type RelateQueriesEventProducer = GenericEventProducer[[]*RelateQueries]
type TopicEventProducer = GenericEventProducer[*TopicContent]

// 创建具体类型生产者的便捷函数
func newRouterEventProducer(chatEvent *ChatEvent, dataPackageId string, parentProducerId string) EventProducer[string] {
	return newGenericEventProducer[string](chatEvent, dataPackageId, parentProducerId, RouterEventType)
}
func newKeywordsEventProducer(chatEvent *ChatEvent, dataPackageId string, parentProducerId string) EventProducer[[]string] {
	return newGenericEventProducer[[]string](chatEvent, dataPackageId, parentProducerId, KeywordsEventType)
}

func newReferenceEventProducer(chatEvent *ChatEvent, dataPackageId string, parentProducerId string) EventProducer[[]*proto.ChatCard] {
	return newGenericEventProducer[[]*proto.ChatCard](chatEvent, dataPackageId, parentProducerId, ReferenceEventType)
}

func newThinkEventProducer(chatEvent *ChatEvent, dataPackageId string, parentProducerId string) EventProducer[string] {
	return newGenericEventProducer[string](chatEvent, dataPackageId, parentProducerId, ThinkEventType)
}

func newAnswerEventProducer(chatEvent *ChatEvent, dataPackageId string, parentProducerId string) EventProducer[*AnswerContent] {
	return newGenericEventProducer[*AnswerContent](chatEvent, dataPackageId, parentProducerId, AnswerEventType)
}

func newRelateQueriesEventProducer(chatEvent *ChatEvent, dataPackageId string, parentProducerId string) EventProducer[[]*RelateQueries] {
	return newGenericEventProducer[[]*RelateQueries](chatEvent, dataPackageId, parentProducerId, RelateQueriesEventType)
}

func newTopicEventProducer(chatEvent *ChatEvent, dataPackageId string, parentProducerId string) EventProducer[*TopicContent] {
	return newGenericEventProducer[*TopicContent](chatEvent, dataPackageId, parentProducerId, TopicEventType)
}

func newChatEventByRetrievalProducer(chatEvent *ChatEvent) *ChatEventByRetrievalProducer {
	cc := &ChatEventByRetrievalProducer{
		chatEvent: chatEvent,
	}
	cc.dataPackageID = chatEvent.dataPackageId
	cc.parentProducerID = chatEvent.producerId
	cc.producerID = uuid.NewString()
	cc.eventType = RetrievalEventType
	// 发起开始事件
	cc.chatEvent.beginBySource(cc.GetDataPackageID(), cc.GetParentProducerID(), cc.GetProducerID(), cc.GetEventType())
	return cc
}

type ChatEventByRetrievalProducer struct {
	chatEventChildBase
	chatEvent *ChatEvent
	// 子类
	mu                      sync.RWMutex
	isDone                  atomic.Bool
	retrievalChildChatEvent []*RetrievalEvent
	producerDoneOnce        sync.Once
}

func (cc *ChatEventByRetrievalProducer) GetCurrRoundRetrievalProducer() *RetrievalEvent {
	cc.mu.RLock()
	defer cc.mu.RUnlock()
	if len(cc.retrievalChildChatEvent) == 0 {
		return nil
	}
	return cc.retrievalChildChatEvent[len(cc.retrievalChildChatEvent)-1]
}

func (cc *ChatEventByRetrievalProducer) GetOrCreateRoundRetrievalProducer() *RetrievalEvent {
	cc.mu.Lock()
	defer cc.mu.Unlock()

	// 判断是否需要创建新的Event
	needNewEvent := len(cc.retrievalChildChatEvent) == 0
	if !needNewEvent {
		lastEvent := cc.retrievalChildChatEvent[len(cc.retrievalChildChatEvent)-1]
		needNewEvent = !cc.isDone.Load() && (lastEvent == nil || lastEvent.IsProducerDone())
	}

	if needNewEvent {
		newEvent := newRetrievalEvent(cc.chatEvent, uuid.NewString(), cc.producerID)
		cc.retrievalChildChatEvent = append(cc.retrievalChildChatEvent, newEvent)
		return newEvent
	}
	return cc.retrievalChildChatEvent[len(cc.retrievalChildChatEvent)-1]
}

// Tracing 记录Tracing
func (cc *ChatEventByRetrievalProducer) Tracing(trace string) *ChatEventByRetrievalProducer {
	if cc.chatEvent == nil || cc.chatEvent.IsProducerDone() || cc.isDone.Load() {
		return cc
	}

	eventMsg := &chatEventMsg{}
	eventMsg.dataPackageID = cc.GetDataPackageID()
	eventMsg.parentProducerID = cc.GetParentProducerID()
	eventMsg.producerID = cc.GetProducerID()
	eventMsg.traceFromEventType = cc.GetEventType()
	eventMsg.eventType = traceEventType
	eventMsg.data = trace
	cc.chatEvent.sendEvent(eventMsg)
	return cc
}

func (cc *ChatEventByRetrievalProducer) Done() {
	cc.producerDoneOnce.Do(func() {
		// 由于每次主流程Done都需要判断子业务Done 所以这里额外处理一下
		// 先判断是否关闭 再加锁 二次DCL一次
		if cc.chatEvent == nil || cc.chatEvent.IsProducerDone() || cc.isDone.Load() {
			return
		}

		cc.mu.Lock()
		defer cc.mu.Unlock()

		// DCL
		if cc.chatEvent == nil || cc.chatEvent.IsProducerDone() || cc.isDone.Load() {
			return
		}

		// 先关闭child event
		if len(cc.retrievalChildChatEvent) > 0 {
			currChildEvent := cc.retrievalChildChatEvent[len(cc.retrievalChildChatEvent)-1]
			if currChildEvent != nil && !currChildEvent.IsProducerDone() {
				currChildEvent.ProducerDone()
			}
		}

		// 再关闭自身
		cc.chatEvent.endBySource(cc.GetDataPackageID(), cc.GetParentProducerID(), cc.GetProducerID(), cc.GetEventType())
		cc.isDone.Store(true)
	})
}

func (cc *ChatEventByRetrievalProducer) getDataPackageIds() []string {
	cc.mu.RLock()
	defer cc.mu.RUnlock()
	dataPackageIds := make([]string, 0)
	for _, retrievalChildChatEvent := range cc.retrievalChildChatEvent {
		dataPackageIds = append(dataPackageIds, retrievalChildChatEvent.dataPackageId)
	}
	return dataPackageIds
}

// ------
// 数据包
type eventBasePackage struct {
	eventProducerMap      sync.Map
	eventProducerMetaMap  sync.Map
	eventProducerStateMap sync.Map
	eventProducerDataMap  sync.Map
	eventBeginTimeMap     sync.Map
	eventDurationMap      sync.Map
	eventTracingMap       sync.Map
	currEventType         atomic.Int32
	historyEventType      sync.Map
}

type BaseEventInfo struct {
	chatEvent   *ChatEvent
	basePackage *eventBasePackage
}

// GetDurationMap 获取耗时
func (e *BaseEventInfo) GetDurationMap() map[ChatEventType]int64 {
	durationMap := make(map[ChatEventType]int64)
	e.basePackage.eventDurationMap.Range(func(key, value interface{}) bool {
		if eventType, isOk := key.(ChatEventType); isOk {
			if eventType > eventBus {
				if duration, isVOk := value.(int64); isVOk {
					durationMap[eventType] = duration
				}
			}
		}
		return true
	})
	return durationMap
}

func (e *BaseEventInfo) getSourceDurationMap() map[ChatEventType]int64 {
	durationMap := make(map[ChatEventType]int64)
	e.basePackage.eventDurationMap.Range(func(key, value interface{}) bool {
		if eventType, isOk := key.(ChatEventType); isOk {
			if duration, isVOk := value.(int64); isVOk {
				durationMap[eventType] = duration
			}
		}
		return true
	})
	return durationMap
}

// GetHistoryEventType 获取历史EventType
func (e *BaseEventInfo) GetHistoryEventType() []ChatEventType {
	historyEventType := make([]ChatEventType, 0)
	e.basePackage.historyEventType.Range(func(key, value any) bool {
		historyEventType = append(historyEventType, key.(ChatEventType))
		return true
	})
	return historyEventType
}

// GetCurrEventType 获取当前EventType
func (e *BaseEventInfo) GetCurrEventType() ChatEventType {
	return ChatEventType(e.basePackage.currEventType.Load())
}

// GetCurrEventState 获取当前Event 状态
func (e *BaseEventInfo) GetCurrEventState() ChatEventState {
	actual, _ := e.basePackage.eventProducerStateMap.LoadOrStore(e.GetCurrEventType(), StateUnknown)
	return actual.(ChatEventState)
}

func (e *BaseEventInfo) GetKeywords() []string {
	actual, isOk := e.basePackage.eventProducerDataMap.Load(KeywordsEventType)
	if !isOk {
		return make([]string, 0)
	}
	return actual.([]string)
}

func (e *BaseEventInfo) GetReferences() []*proto.ChatCard {
	actual, isOk := e.basePackage.eventProducerDataMap.Load(ReferenceEventType)
	if !isOk {
		return make([]*proto.ChatCard, 0)
	}
	return actual.([]*proto.ChatCard)
}

func (e *BaseEventInfo) GetThinkContent() string {
	actual, isOk := e.basePackage.eventProducerDataMap.Load(ThinkEventType)
	if !isOk {
		return ""
	}
	return actual.(string)
}

func (e *BaseEventInfo) GetAnswerContent() *AnswerContent {
	actual, isOk := e.basePackage.eventProducerDataMap.Load(AnswerEventType)
	if !isOk {
		return nil
	}
	return actual.(*AnswerContent)
}

func newEventInfo(chatEvent *ChatEvent) *EventInfo {
	info := &EventInfo{}
	info.chatEvent = chatEvent
	store, isExist := chatEvent.eventStateBucket.Load(chatEvent.dataPackageId)
	if !isExist {
		storeNew, _ := chatEvent.eventStateBucket.LoadOrStore(chatEvent.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	info.basePackage = store.(*eventBasePackage)
	return info
}

type EventInfo struct {
	BaseEventInfo
}

func (e *EventInfo) GetTraceJson() (string, error) {
	traces := make([]*EventTrace, 0)
	// 获取数据桶
	e.chatEvent.eventStateBucket.Range(func(_, dataStoreSource any) bool {
		if dataStore, isStoreOk := dataStoreSource.(*eventBasePackage); isStoreOk {
			dataStore.eventProducerMetaMap.Range(func(key, _ any) bool {
				if eventMetaInfo, isMetaOk := key.(eventMeta); isMetaOk {
					if eventMetaInfo.GetEventType() != unknown && eventMetaInfo.GetEventType() != traceEventType && eventMetaInfo.GetProducerID() != "" {
						et := &EventTrace{
							ParentEventId: eventMetaInfo.GetParentProducerID(),
							EventId:       eventMetaInfo.GetProducerID(),
							EventType:     eventMetaInfo.GetEventType(),
						}

						// 开始时间戳
						if beginTimeMs, isOk := dataStore.eventBeginTimeMap.Load(eventMetaInfo.GetEventType()); isOk {
							et.BeginTimeMs = beginTimeMs.(time.Time).UnixMilli()
						}

						// 执行时间MS
						if durationMs, isOk := dataStore.eventDurationMap.Load(eventMetaInfo.GetEventType()); isOk {
							et.ProcessingDurationMs = durationMs.(int64)
						}

						// 执行状态
						if state, isOk := dataStore.eventProducerStateMap.Load(eventMetaInfo.GetEventType()); isOk {
							et.EventState = state.(ChatEventState)
						}

						// 执行结果
						if res, isOk := dataStore.eventProducerDataMap.Load(eventMetaInfo.GetEventType()); isOk {
							et.Result = res
						}

						// Trace
						if traceRes, isOk := dataStore.eventTracingMap.Load(eventMetaInfo.GetEventType()); isOk {
							et.Trace = traceRes.(string)
						}
						traces = append(traces, et)
					}

				}
				return true
			})
			return true
		}
		return true
	})

	traceJsonStr, err := eventTreeToCompactJSON(traces)
	//traceJsonStr, err := eventTreeToJSON(traces)
	return traceJsonStr, err
}

func (e *EventInfo) GetRetrieval() []*RetrievalEventInfo {
	eventInfos := make([]*RetrievalEventInfo, 0)
	if value, isExist := e.chatEvent.getRetrievalEventProducer(); isExist {
		retrievalProducer := value.(*ChatEventByRetrievalProducer)
		for _, dataPackageId := range retrievalProducer.getDataPackageIds() {
			store, isExist := e.chatEvent.eventStateBucket.Load(dataPackageId)
			if !isExist {
				storeNew, _ := e.chatEvent.eventStateBucket.LoadOrStore(dataPackageId, &eventBasePackage{})
				store = storeNew
			}
			info := newRetrievalEventInfo(store.(*eventBasePackage))
			if (eventBus == info.GetCurrEventType()) || info.GetCurrEventType() == unknown || info.GetCurrEventState() == StateUnknown {
				continue
			}
			eventInfos = append(eventInfos, info)
		}
	}
	return eventInfos
}

func (e *EventInfo) GetRelateQueries() []*RelateQueries {
	actual, isOk := e.basePackage.eventProducerDataMap.Load(RelateQueriesEventType)
	if !isOk {
		return make([]*RelateQueries, 0)
	}
	return actual.([]*RelateQueries)
}

func newRetrievalEventInfo(basePackage *eventBasePackage) *RetrievalEventInfo {
	info := &RetrievalEventInfo{}
	info.basePackage = basePackage
	return info
}

type RetrievalEventInfo struct {
	BaseEventInfo
}

func (e *RetrievalEventInfo) GetTopic() *TopicContent {
	actual, isOk := e.basePackage.eventProducerDataMap.Load(TopicEventType)
	if !isOk {
		return &TopicContent{}
	}
	return actual.(*TopicContent)
}
