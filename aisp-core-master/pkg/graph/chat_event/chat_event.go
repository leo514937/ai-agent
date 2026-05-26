package chat_event

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zag-driver/pkg/framework/constant"
	"git.in.zhihu.com/zrec/zag-driver/pkg/framework/tools"
	"github.com/google/uuid"
	"github.com/pkg/errors"
)

func NewChatEvent(ctx context.Context, callback func(data *EventInfo)) *ChatEvent {
	return newChatEventByParent(ctx, "", callback)
}

func newChatEventByParent(ctx context.Context, parentProducerId string, callback func(data *EventInfo)) *ChatEvent {
	var traceId string
	if ctx.Value(constant.TraceIdKey) != nil {
		traceId = ctx.Value(constant.TraceIdKey).(string)
	} else {
		traceId = tools.GetNextId()
	}

	event := &ChatEvent{
		ctx:                     ctx,
		traceId:                 traceId,
		producerId:              uuid.NewString(),
		parentProducerId:        parentProducerId,
		dataPackageId:           uuid.NewString(),
		eventType:               eventBus,
		workspace:               newChatEventWork[any](10000),
		eventProcessor:          newEventProcessorByIgnore([]ChatEventType{unknown, RetrievalEventType}),
		retrievalEventProcessor: newEventProcessorByAllow([]ChatEventType{RetrievalEventType}),
		callback:                callback,
	}
	event.doConsumer()
	event.begin()
	return event
}

type ChatEvent struct {
	ctx                     context.Context
	traceId                 string
	producerId              string
	parentProducerId        string
	dataPackageId           string
	eventType               ChatEventType
	currType                ChatEventType
	workspace               *ChatEventWorker[any]
	callback                func(data *EventInfo)
	producerDoneOnce        sync.Once
	eventStateBucket        sync.Map
	eventProcessor          *EventProcessor
	retrievalEventProcessor *EventProcessor
}

func (c *ChatEvent) doConsumer() {
	// 消费event 事件
	c.workspace.Consumer(func(eventMsg any) error {
		if c.IsProducerDone() {
			return nil
		}
		if eventMsg == nil {
			return EventError{
				EventType: unknown,
				Operation: "validate_message",
				Err:       errors.New("received nil event message"),
			}
		}

		// 类型安全的消息处理
		msg, ok := eventMsg.(*chatEventMsg)
		if !ok {
			return EventError{
				EventType: unknown,
				Operation: "cast_message",
				Err:       fmt.Errorf("expected *chatEventMsg, got %T", eventMsg),
			}
		}

		return c.processMessage(msg)
	})
}

// processMessage 处理单个事件消息（重构后的核心逻辑）
func (c *ChatEvent) processMessage(msg *chatEventMsg) error {
	// 获取或创建数据包
	dataPackage, err := c.getOrCreateDataPackage(msg.GetDataPackageID())
	if err != nil {
		return err
	}

	// 检查事件状态
	if cErr, isEnd := c.checkEventState(msg, dataPackage); cErr != nil || isEnd {
		return err
	}

	// 更新事件状态和历史
	c.updateEventMetadata(msg, dataPackage)

	// 处理特殊的 Retrieve 阶段逻辑
	c.handleRetrieveStageLogic(msg)

	// 使用事件处理器处理数据
	if err := c.handleEventData(c.eventProcessor, msg, dataPackage); err != nil {
		return err
	}

	// 检查是否需要停止
	if c.shouldStopProcessing(msg) {
		c.workspace.ProducerDone()
		return nil
	}

	// 触发回调
	if msg.GetEventType() != unknown && msg.GetEventType() != traceEventType {
		if msg.GetDataPackageID() == c.dataPackageId {
			if msg.GetEventType() != eventBus {
				c.safeCallback(msg)
			}
		} else {
			c.safeCallback(msg)
		}
	}

	// 特殊处理Retrieval
	if err := c.handleEventData(c.retrievalEventProcessor, msg, dataPackage); err != nil {
		return err
	}
	return nil
}

// getOrCreateDataPackage 获取或创建数据包
func (c *ChatEvent) getOrCreateDataPackage(dataPackageID string) (*eventBasePackage, error) {
	store, isExist := c.eventStateBucket.Load(dataPackageID)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(dataPackageID, &eventBasePackage{})
		store = storeNew
	}
	dataPackage, ok := store.(*eventBasePackage)
	if !ok {
		return nil, EventError{
			EventType: unknown,
			Operation: "get_data_package",
			Err:       fmt.Errorf("failed to cast data package"),
		}
	}
	return dataPackage, nil
}

// checkEventState 检查事件状态
func (c *ChatEvent) checkEventState(msg *chatEventMsg, dataPackage *eventBasePackage) (error, bool) {
	state, _ := dataPackage.eventProducerStateMap.LoadOrStore(msg.GetEventType(), StateUnknown)
	currentState, ok := state.(ChatEventState)
	if !ok {
		return EventError{
			EventType: msg.GetEventType(),
			Operation: "check_state",
			Err:       fmt.Errorf("invalid state type"),
		}, false
	}

	// 已 Done 则不继续执行
	if currentState == StateEnd {
		return nil, true
	}
	return nil, false
}

// updateEventMetadata 更新事件元数据
func (c *ChatEvent) updateEventMetadata(msg *chatEventMsg, dataPackage *eventBasePackage) {
	// 更新当前最新的 event type
	if msg.GetEventType() > 0 && dataPackage.currEventType.Load() < int32(msg.GetEventType()) {
		dataPackage.currEventType.Store(int32(msg.GetEventType()))
	}

	// 存放历史 event type
	if _, isOk := dataPackage.historyEventType.Load(msg.GetEventType()); !isOk {
		dataPackage.historyEventType.Store(msg.GetEventType(), 0)
	}

	// 更新Meta信息
	eventMetaKey := eventMeta{
		parentProducerID: msg.GetParentProducerID(),
		producerID:       msg.GetProducerID(),
		eventType:        msg.GetEventType(),
	}
	if _, isOk := dataPackage.eventProducerMetaMap.Load(eventMetaKey); !isOk {
		dataPackage.eventProducerMetaMap.Store(eventMetaKey, 0)
	}

	// 修改当前state
	state, _ := dataPackage.eventProducerStateMap.Load(msg.GetEventType())
	if state != msg.GetStage() {
		dataPackage.eventProducerStateMap.Store(msg.GetEventType(), msg.GetStage())
	}
}

// handleRetrieveStageLogic 处理 Retrieve 阶段的特殊逻辑
func (c *ChatEvent) handleRetrieveStageLogic(msg *chatEventMsg) {
	if msg.GetDataPackageID() != c.dataPackageId {
		if pStore, ok := c.eventStateBucket.Load(c.dataPackageId); ok {
			if pDataPackage, ok := pStore.(*eventBasePackage); ok {
				if pDataPackage.currEventType.Load() == int32(RetrievalEventType) {
					pDataPackage.eventProducerStateMap.CompareAndSwap(RetrievalEventType, StateBegin, StateProcessing)
				}
			}
		}
	}
}

// shouldStopProcessing 检查是否需要停止处理
func (c *ChatEvent) shouldStopProcessing(msg *chatEventMsg) bool {
	return StateEnd == msg.GetStage() && eventBus == msg.GetEventType() && msg.IsDone()
}

// handleEventData 使用事件处理器处理数据
func (c *ChatEvent) handleEventData(eventProcessor *EventProcessor, msg *chatEventMsg, dataPackage *eventBasePackage) error {
	if eventProcessor != nil {
		return eventProcessor.HandleEvent(msg, dataPackage, c)
	}
	return nil
}

// safeCallback 安全地调用回调函数
func (c *ChatEvent) safeCallback(msg *chatEventMsg) {
	logger := log.WithFields(c.ctx, map[string]interface{}{
		"func": "ChatEvent.callback",
	})
	defer func() {
		if r := recover(); r != nil {
			logger.Warnf(c.ctx, "panic recovered for event %s: %v\n", msg.GetEventType(), r)
		}
	}()

	if c.callback != nil {
		eventInfo := newEventInfo(c)
		c.callback(eventInfo)
		//traceJson, _ := eventInfo.GetTraceJson()
		//logger.Infof(c.ctx, "traceId: %s eventType:%s => %s\n", c.traceId, msg.GetEventType(), traceJson)
	}
}

func (c *ChatEvent) sendEvent(eventMsg any) {
	if eventMsg == nil {
		return
	}

	c.workspace.Producer(func(producer *ChatEventWorkerProducer[any]) {
		_ = producer.Put(eventMsg)
	})
}

func (c *ChatEvent) GetAllEventData() *EventInfo {
	return newEventInfo(c)
}

func (c *ChatEvent) begin() {
	c.beginBySource(c.dataPackageId, c.parentProducerId, c.producerId, c.eventType)
}
func (c *ChatEvent) beginBySource(dataPackageId string, parentProducerId string, producerId string, eventType ChatEventType) {
	// 关闭自身
	eventMsg := &chatEventMsg{}
	eventMsg.dataPackageID = dataPackageId
	eventMsg.parentProducerID = parentProducerId
	eventMsg.producerID = producerId
	eventMsg.eventType = eventType
	eventMsg.stage = StateBegin
	c.sendEvent(eventMsg)
}

func (c *ChatEvent) end() {
	c.endBySource(c.dataPackageId, c.parentProducerId, c.producerId, c.eventType)
}

func (c *ChatEvent) endBySource(dataPackageId string, parentProducerId string, producerId string, eventType ChatEventType) {
	// 关闭自身
	eventMsg := &chatEventMsg{}
	eventMsg.dataPackageID = dataPackageId
	eventMsg.parentProducerID = parentProducerId
	eventMsg.producerID = producerId
	eventMsg.eventType = eventType
	eventMsg.stage = StateEnd
	c.sendEvent(eventMsg)
}

func (c *ChatEvent) done() {
	c.doneBySource(c.dataPackageId, c.parentProducerId, c.producerId, c.eventType)
}

func (c *ChatEvent) doneBySource(dataPackageId string, parentProducerId string, producerId string, eventType ChatEventType) {
	// 关闭自身
	eventMsg := &chatEventMsg{}
	eventMsg.dataPackageID = dataPackageId
	eventMsg.parentProducerID = parentProducerId
	eventMsg.producerID = producerId
	eventMsg.eventType = eventType
	eventMsg.isDone = true
	eventMsg.stage = StateEnd
	c.sendEvent(eventMsg)
}

func (c *ChatEvent) getProducerKey(eventType ChatEventType, dataPackageId string) string {
	return fmt.Sprintf("%s:%s", eventType, dataPackageId)
}

func (c *ChatEvent) GetRetrievalEventProducer() *ChatEventByRetrievalProducer {
	store, isExist := c.eventStateBucket.Load(c.dataPackageId)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(c.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	dataPackage := store.(*eventBasePackage)
	// 创建复合键
	key := c.getProducerKey(RetrievalEventType, c.dataPackageId)
	// 为这个组合创建OnceValue函数
	onceValueInterface, _ := dataPackage.eventProducerMap.LoadOrStore(key, sync.OnceValue(func() *ChatEventByRetrievalProducer {
		return newChatEventByRetrievalProducer(c)
	}))
	// 调用OnceValue函数
	return onceValueInterface.(func() *ChatEventByRetrievalProducer)()
}
func (c *ChatEvent) getRetrievalEventProducer() (any, bool) {
	store, isExist := c.eventStateBucket.Load(c.dataPackageId)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(c.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	dataPackage := store.(*eventBasePackage)
	// 创建复合键
	key := c.getProducerKey(RetrievalEventType, c.dataPackageId)
	onceValueInterface, ok := dataPackage.eventProducerMap.Load(key)
	if !ok {
		return nil, false
	}
	return onceValueInterface.(func() *ChatEventByRetrievalProducer)(), true
}

func (c *ChatEvent) GetRouterProducer() EventProducer[string] {
	return c.getRouterProducer(c.dataPackageId, c.producerId)
}

func (c *ChatEvent) getRouterProducer(dataPackageId string, producerId string) EventProducer[string] {
	store, isExist := c.eventStateBucket.Load(c.dataPackageId)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(c.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	dataPackage := store.(*eventBasePackage)

	// 创建复合键
	key := c.getProducerKey(RouterEventType, dataPackageId)
	// 为这个组合创建OnceValue函数
	onceValueInterface, _ := dataPackage.eventProducerMap.LoadOrStore(key, sync.OnceValue(func() EventProducer[string] {
		return newRouterEventProducer(c, dataPackageId, producerId)
	}))
	// 调用OnceValue函数
	return onceValueInterface.(func() EventProducer[string])()
}

func (c *ChatEvent) GetKeywordsProducer() EventProducer[[]string] {
	return c.getKeywordsProducer(c.dataPackageId, c.producerId)
}

func (c *ChatEvent) getKeywordsProducer(dataPackageId string, producerId string) EventProducer[[]string] {
	store, isExist := c.eventStateBucket.Load(c.dataPackageId)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(c.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	dataPackage := store.(*eventBasePackage)
	// 创建复合键
	key := c.getProducerKey(KeywordsEventType, dataPackageId)
	// 为这个组合创建OnceValue函数
	onceValueInterface, _ := dataPackage.eventProducerMap.LoadOrStore(key, sync.OnceValue(func() EventProducer[[]string] {
		return newKeywordsEventProducer(c, dataPackageId, producerId)
	}))
	// 调用OnceValue函数
	return onceValueInterface.(func() EventProducer[[]string])()
}

func (c *ChatEvent) GetReferenceProducer() EventProducer[[]*proto.ChatCard] {
	return c.getReferenceProducer(c.dataPackageId, c.producerId)
}

func (c *ChatEvent) getReferenceProducer(dataPackageId string, producerId string) EventProducer[[]*proto.ChatCard] {
	store, isExist := c.eventStateBucket.Load(c.dataPackageId)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(c.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	dataPackage := store.(*eventBasePackage)
	// 创建复合键
	key := c.getProducerKey(ReferenceEventType, dataPackageId)
	// 为这个组合创建OnceValue函数
	onceValueInterface, _ := dataPackage.eventProducerMap.LoadOrStore(key, sync.OnceValue(func() EventProducer[[]*proto.ChatCard] {
		return newReferenceEventProducer(c, dataPackageId, producerId)
	}))
	// 调用OnceValue函数
	return onceValueInterface.(func() EventProducer[[]*proto.ChatCard])()
}

func (c *ChatEvent) GetThinkProducer() EventProducer[string] {
	return c.getThinkProducer(c.dataPackageId, c.producerId)
}

func (c *ChatEvent) getThinkProducer(dataPackageId string, producerId string) EventProducer[string] {
	store, isExist := c.eventStateBucket.Load(c.dataPackageId)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(c.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	dataPackage := store.(*eventBasePackage)

	// 创建复合键
	key := c.getProducerKey(ThinkEventType, dataPackageId)
	// 为这个组合创建OnceValue函数
	onceValueInterface, _ := dataPackage.eventProducerMap.LoadOrStore(key, sync.OnceValue(func() EventProducer[string] {
		return newThinkEventProducer(c, dataPackageId, producerId)
	}))
	// 调用OnceValue函数
	return onceValueInterface.(func() EventProducer[string])()
}

func (c *ChatEvent) GetAnswerProducer() EventProducer[*AnswerContent] {
	return c.getAnswerProducer(c.dataPackageId, c.producerId)
}

func (c *ChatEvent) getAnswerProducer(dataPackageId string, producerId string) EventProducer[*AnswerContent] {
	store, isExist := c.eventStateBucket.Load(c.dataPackageId)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(c.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	dataPackage := store.(*eventBasePackage)
	// 创建复合键
	key := c.getProducerKey(AnswerEventType, dataPackageId)
	// 为这个组合创建OnceValue函数
	onceValueInterface, _ := dataPackage.eventProducerMap.LoadOrStore(key, sync.OnceValue(func() EventProducer[*AnswerContent] {
		return newAnswerEventProducer(c, dataPackageId, producerId)
	}))
	// 调用OnceValue函数
	return onceValueInterface.(func() EventProducer[*AnswerContent])()
}

func (c *ChatEvent) GetRelateQueriesProducer() EventProducer[[]*RelateQueries] {
	return c.getRelateQueriesProducer(c.dataPackageId, c.producerId)
}

func (c *ChatEvent) getRelateQueriesProducer(dataPackageId string, producerId string) EventProducer[[]*RelateQueries] {
	store, isExist := c.eventStateBucket.Load(c.dataPackageId)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(c.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	dataPackage := store.(*eventBasePackage)
	// 创建复合键
	key := c.getProducerKey(RelateQueriesEventType, dataPackageId)
	// 为这个组合创建OnceValue函数
	onceValueInterface, _ := dataPackage.eventProducerMap.LoadOrStore(key, sync.OnceValue(func() EventProducer[[]*RelateQueries] {
		return newRelateQueriesEventProducer(c, dataPackageId, producerId)
	}))
	// 调用OnceValue函数
	return onceValueInterface.(func() EventProducer[[]*RelateQueries])()
}

func (c *ChatEvent) GetTopicProducer() EventProducer[*TopicContent] {
	return c.getTopicProducer(c.dataPackageId, c.producerId)
}

func (c *ChatEvent) getTopicProducer(dataPackageId string, producerId string) EventProducer[*TopicContent] {
	store, isExist := c.eventStateBucket.Load(c.dataPackageId)
	if !isExist {
		storeNew, _ := c.eventStateBucket.LoadOrStore(c.dataPackageId, &eventBasePackage{})
		store = storeNew
	}
	dataPackage := store.(*eventBasePackage)
	// 创建复合键
	key := c.getProducerKey(TopicEventType, dataPackageId)
	// 为这个组合创建OnceValue函数
	onceValueInterface, _ := dataPackage.eventProducerMap.LoadOrStore(key, sync.OnceValue(func() EventProducer[*TopicContent] {
		return newTopicEventProducer(c, dataPackageId, producerId)
	}))
	// 调用OnceValue函数
	return onceValueInterface.(func() EventProducer[*TopicContent])()
}

func (c *ChatEvent) IsProducerDone() bool {
	return c.workspace.IsProducerDone()
}

func (c *ChatEvent) ProducerDone() {
	c.producerDoneOnce.Do(func() {
		// 先关闭未关闭的子producer
		if c.GetAllEventData().GetCurrEventState() != StateEnd {
			switch c.GetAllEventData().GetCurrEventType() {
			case TopicEventType:
				c.GetTopicProducer().Done()
			case RelateQueriesEventType:
				c.GetRelateQueriesProducer().Done()
			case RetrievalEventType:
				retrievalProducer, isOk := c.getRetrievalEventProducer()
				if isOk {
					retrievalProducer.(*ChatEventByRetrievalProducer).Done()
				}
			case KeywordsEventType:
				c.GetKeywordsProducer().Done()
			case ReferenceEventType:
				c.GetReferenceProducer().Done()
			case ThinkEventType:
				c.GetThinkProducer().Done()
			case AnswerEventType:
				c.GetAnswerProducer().Done()
			}
		}

		// 关闭自身
		c.done()
	})
}

func (c *ChatEvent) AWait() {
	_ = c.workspace.Wait()
}

// NewRetrievalEvent 装饰器包装一下 不允许调用 GetRetrievalEventProducer
func newRetrievalEvent(parentEventObj *ChatEvent, dataPackageId string, parentProduceId string) *RetrievalEvent {
	event := &RetrievalEvent{
		dataPackageId:    dataPackageId,
		parentEventObj:   parentEventObj,
		parentProducerId: parentProduceId,
		producerId:       uuid.NewString(),
		eventType:        eventBus,
	}
	// 触发开始事件
	event.parentEventObj.beginBySource(event.dataPackageId, event.parentProducerId, event.producerId, event.eventType)
	return event
}

type RetrievalEvent struct {
	dataPackageId    string
	parentEventObj   *ChatEvent
	parentProducerId string
	producerId       string
	eventType        ChatEventType
	producerDoneOnce sync.Once
	isDone           atomic.Bool
}

func (c *RetrievalEvent) GetTopicProducer() EventProducer[*TopicContent] {
	return c.parentEventObj.getTopicProducer(c.dataPackageId, c.producerId)
}

func (c *RetrievalEvent) GetKeywordsProducer() EventProducer[[]string] {
	return c.parentEventObj.getKeywordsProducer(c.dataPackageId, c.producerId)
}

func (c *RetrievalEvent) GetReferenceProducer() EventProducer[[]*proto.ChatCard] {
	return c.parentEventObj.getReferenceProducer(c.dataPackageId, c.producerId)
}

func (c *RetrievalEvent) GetAnswerProducer() EventProducer[*AnswerContent] {
	return c.parentEventObj.getAnswerProducer(c.dataPackageId, c.producerId)
}

func (c *RetrievalEvent) IsProducerDone() bool {
	return c.isDone.Load()
}

func (c *RetrievalEvent) ProducerDone() {
	c.producerDoneOnce.Do(func() {
		// 先关闭未关闭的子producer
		if store, isExist := c.parentEventObj.eventStateBucket.Load(c.dataPackageId); isExist {
			retrievalEventInfo := newRetrievalEventInfo(store.(*eventBasePackage))
			if retrievalEventInfo.GetCurrEventState() != StateEnd {
				switch retrievalEventInfo.GetCurrEventType() {
				case TopicEventType:
					c.GetTopicProducer().Done()
				case ReferenceEventType:
					c.GetReferenceProducer().Done()
				case KeywordsEventType:
					c.GetKeywordsProducer().Done()
				case AnswerEventType:
					c.GetAnswerProducer().Done()
				}
			}
		}

		// 发送关闭事件
		c.parentEventObj.endBySource(c.dataPackageId, c.parentProducerId, c.producerId, c.eventType)
		c.isDone.Store(true)
	})
}
