package chat_event

import (
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"github.com/samber/lo"
)

// EventError 事件处理错误
type EventError struct {
	EventType ChatEventType
	Operation string
	Err       error
}

func (e EventError) Error() string {
	return fmt.Sprintf("event error [%s] in %s: %v", e.EventType, e.Operation, e.Err)
}

// EventHandler 事件处理器接口
type EventHandler interface {
	Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error
	EventType() ChatEventType
	CanHandle(eventType ChatEventType) bool
}

// BaseEventHandler 基础事件处理器
type BaseEventHandler struct {
	eventType ChatEventType
}

func (h *BaseEventHandler) EventType() ChatEventType {
	return h.eventType
}

func (h *BaseEventHandler) CanHandle(eventType ChatEventType) bool {
	return h.eventType == eventType
}

// RouterEventHandler Router事件处理器
type RouterEventHandler struct {
	BaseEventHandler
}

func newRouterEventHandler() *RouterEventHandler {
	return &RouterEventHandler{
		BaseEventHandler: BaseEventHandler{eventType: RouterEventType},
	}
}

func (h *RouterEventHandler) Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	// 处理空数据的情况
	if msg.data == nil {
		return nil // 空数据不是错误，直接跳过
	}

	eventData, ok := msg.data.(string)
	if !ok {
		return EventError{
			EventType: RouterEventType,
			Operation: "type_assertion",
			Err:       fmt.Errorf("expected string, got %T", msg.data),
		}
	}

	dataPackage.eventProducerDataMap.Store(msg.GetEventType(), eventData)
	return nil
}

// KeywordsEventHandler 关键词事件处理器
type KeywordsEventHandler struct {
	BaseEventHandler
}

func newKeywordsEventHandler() *KeywordsEventHandler {
	return &KeywordsEventHandler{
		BaseEventHandler: BaseEventHandler{eventType: KeywordsEventType},
	}
}

func (h *KeywordsEventHandler) Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	// 处理空数据的情况
	if msg.data == nil {
		return nil // 空数据不是错误，直接跳过
	}

	eventData, ok := msg.data.([]string)
	if !ok {
		return EventError{
			EventType: KeywordsEventType,
			Operation: "type_assertion",
			Err:       fmt.Errorf("expected []string, got %T", msg.data),
		}
	}

	keywords, _ := dataPackage.eventProducerDataMap.LoadOrStore(msg.GetEventType(), make([]string, 0))
	keywordsData, ok := keywords.([]string)
	if !ok {
		return EventError{
			EventType: KeywordsEventType,
			Operation: "load_existing_data",
			Err:       fmt.Errorf("existing data type assertion failed"),
		}
	}

	keywordsData = append(keywordsData, eventData...)
	dataPackage.eventProducerDataMap.Store(msg.GetEventType(), keywordsData)
	return nil
}

// ReferenceEventHandler 召回内容事件处理器
type ReferenceEventHandler struct {
	BaseEventHandler
}

func newReferenceEventHandler() *ReferenceEventHandler {
	return &ReferenceEventHandler{
		BaseEventHandler: BaseEventHandler{eventType: ReferenceEventType},
	}
}

func (h *ReferenceEventHandler) Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	// 处理空数据的情况
	if msg.data == nil {
		return nil // 空数据不是错误，直接跳过
	}

	eventData, ok := msg.data.([]*proto.ChatCard)
	if !ok {
		return EventError{
			EventType: ReferenceEventType,
			Operation: "type_assertion",
			Err:       fmt.Errorf("expected []*proto.ChatCard, got %T", msg.data),
		}
	}

	cards, _ := dataPackage.eventProducerDataMap.LoadOrStore(msg.GetEventType(), make([]*proto.ChatCard, 0))
	cardsData, ok := cards.([]*proto.ChatCard)
	if !ok {
		return EventError{
			EventType: ReferenceEventType,
			Operation: "load_existing_data",
			Err:       fmt.Errorf("existing data type assertion failed"),
		}
	}

	cardsData = append(cardsData, eventData...)
	dataPackage.eventProducerDataMap.Store(msg.GetEventType(), cardsData)
	return nil
}

// ThinkEventHandler 思考事件处理器
type ThinkEventHandler struct {
	BaseEventHandler
}

func newThinkEventHandler() *ThinkEventHandler {
	return &ThinkEventHandler{
		BaseEventHandler: BaseEventHandler{eventType: ThinkEventType},
	}
}

func (h *ThinkEventHandler) Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	// 处理空数据的情况
	if msg.data == nil {
		return nil // 空数据不是错误，直接跳过
	}

	eventData, ok := msg.data.(string)
	if !ok {
		return EventError{
			EventType: ThinkEventType,
			Operation: "type_assertion",
			Err:       fmt.Errorf("expected string, got %T", msg.data),
		}
	}

	dataPackage.eventProducerDataMap.Store(msg.GetEventType(), eventData)
	return nil
}

// AnswerEventHandler 答案事件处理器
type AnswerEventHandler struct {
	BaseEventHandler
}

func newAnswerEventHandler() *AnswerEventHandler {
	return &AnswerEventHandler{
		BaseEventHandler: BaseEventHandler{eventType: AnswerEventType},
	}
}

func (h *AnswerEventHandler) Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	// 处理空数据的情况
	if msg.data == nil {
		return nil // 空数据不是错误，直接跳过
	}

	eventData, ok := msg.data.(*AnswerContent)
	if !ok {
		return EventError{
			EventType: AnswerEventType,
			Operation: "type_assertion",
			Err:       fmt.Errorf("expected *AnswerContent, got %T", msg.data),
		}
	}

	dataPackage.eventProducerDataMap.Store(msg.GetEventType(), eventData)
	return nil
}

// RelateQueriesEventHandler 相关查询事件处理器
type RelateQueriesEventHandler struct {
	BaseEventHandler
}

func newRelateQueriesEventHandler() *RelateQueriesEventHandler {
	return &RelateQueriesEventHandler{
		BaseEventHandler: BaseEventHandler{eventType: RelateQueriesEventType},
	}
}

func (h *RelateQueriesEventHandler) Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	// 处理空数据的情况
	if msg.data == nil {
		return nil // 空数据不是错误，直接跳过
	}

	eventData, ok := msg.data.([]*RelateQueries)
	if !ok {
		return EventError{
			EventType: RelateQueriesEventType,
			Operation: "type_assertion",
			Err:       fmt.Errorf("expected []*RelateQueries, got %T", msg.data),
		}
	}

	relateQueries, _ := dataPackage.eventProducerDataMap.LoadOrStore(msg.GetEventType(), make([]*RelateQueries, 0))
	relateQueriesData, ok := relateQueries.([]*RelateQueries)
	if !ok {
		return EventError{
			EventType: RelateQueriesEventType,
			Operation: "load_existing_data",
			Err:       fmt.Errorf("existing data type assertion failed"),
		}
	}

	relateQueriesData = append(relateQueriesData, eventData...)
	dataPackage.eventProducerDataMap.Store(msg.GetEventType(), relateQueriesData)
	return nil
}

// TopicEventHandler 主题事件处理器
type TopicEventHandler struct {
	BaseEventHandler
}

func newTopicEventHandler() *TopicEventHandler {
	return &TopicEventHandler{
		BaseEventHandler: BaseEventHandler{eventType: TopicEventType},
	}
}

func (h *TopicEventHandler) Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	// 处理空数据的情况
	if msg.data == nil {
		return nil // 空数据不是错误，直接跳过
	}

	eventData, ok := msg.data.(*TopicContent)
	if !ok {
		return EventError{
			EventType: TopicEventType,
			Operation: "type_assertion",
			Err:       fmt.Errorf("expected TopicContent, got %T", msg.data),
		}
	}

	dataPackage.eventProducerDataMap.Store(msg.GetEventType(), eventData)
	return nil
}

// RetrievalEventHandler 主题事件处理器
type RetrievalEventHandler struct {
	BaseEventHandler
}

func newRetrievalEventHandler() *RetrievalEventHandler {
	return &RetrievalEventHandler{
		BaseEventHandler: BaseEventHandler{eventType: RetrievalEventType},
	}
}

func (h *RetrievalEventHandler) Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	// 如果是Retrieve结束
	// ...
	return nil
}

// TraceEventHandler 日志事件处理器
type TraceEventHandler struct {
	BaseEventHandler
}

func newTraceEventHandler() *TraceEventHandler {
	return &TraceEventHandler{
		BaseEventHandler: BaseEventHandler{eventType: traceEventType},
	}
}

func (h *TraceEventHandler) Handle(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	// 处理空数据的情况
	if msg.data == nil {
		return nil // 空数据不是错误，直接跳过
	}

	traceData, ok := msg.data.(string)
	if !ok {
		return EventError{
			EventType: traceEventType,
			Operation: "type_assertion",
			Err:       fmt.Errorf("expected string, got %T", msg.data),
		}
	}

	dataPackage.eventTracingMap.Store(msg.GetTraceFromEventType(), traceData)
	return nil
}

// EventProcessor 事件处理器管理器
type EventProcessor struct {
	handlers    map[ChatEventType]EventHandler
	ignoreTypes []ChatEventType
	allowTypes  []ChatEventType
}

func newEventProcessorByIgnore(ignoreTypes []ChatEventType) *EventProcessor {
	return newEventProcessor([]ChatEventType{}, ignoreTypes)
}

func newEventProcessorByAllow(allowTypes []ChatEventType) *EventProcessor {
	return newEventProcessor(allowTypes, []ChatEventType{})
}

func newEventProcessor(allowTypes []ChatEventType, ignoreTypes []ChatEventType) *EventProcessor {
	processor := &EventProcessor{
		handlers:    make(map[ChatEventType]EventHandler),
		ignoreTypes: ignoreTypes,
		allowTypes:  allowTypes,
	}

	// 注册所有处理器
	processor.RegisterHandler(newRetrievalEventHandler())
	processor.RegisterHandler(newKeywordsEventHandler())
	processor.RegisterHandler(newReferenceEventHandler())
	processor.RegisterHandler(newThinkEventHandler())
	processor.RegisterHandler(newAnswerEventHandler())
	processor.RegisterHandler(newRelateQueriesEventHandler())
	processor.RegisterHandler(newTopicEventHandler())
	processor.RegisterHandler(newRouterEventHandler())
	processor.RegisterHandler(newTraceEventHandler())

	return processor
}

func (p *EventProcessor) RegisterHandler(handler EventHandler) {
	p.handlers[handler.EventType()] = handler
}

func (p *EventProcessor) HandleEvent(msg *chatEventMsg, dataPackage *eventBasePackage, chatEvent *ChatEvent) error {
	if len(p.ignoreTypes) > 0 && lo.Contains(p.ignoreTypes, msg.GetEventType()) {
		return nil
	}

	if len(p.allowTypes) > 0 && !lo.Contains(p.allowTypes, msg.GetEventType()) {
		return nil
	}

	// 处理执行时间
	if msg.GetStage() == StateBegin {
		dataPackage.eventBeginTimeMap.Store(msg.GetEventType(), time.Now())
		return nil
	}
	if msg.GetStage() == StateEnd {
		beginTime, _ := dataPackage.eventBeginTimeMap.LoadOrStore(msg.GetEventType(), time.Now())
		if bt, isOk := beginTime.(time.Time); isOk {
			dataPackage.eventDurationMap.Store(msg.GetEventType(), max(time.Now().Sub(bt).Milliseconds(), 1))
		}
		if msg.GetEventType() != RetrievalEventType {
			return nil
		}
	}

	handler, exists := p.handlers[msg.GetEventType()]
	if !exists {
		return EventError{
			EventType: msg.GetEventType(),
			Operation: "find_handler",
			Err:       fmt.Errorf("no handler found for event type %s", msg.GetEventType()),
		}
	}

	return handler.Handle(msg, dataPackage, chatEvent)
}
