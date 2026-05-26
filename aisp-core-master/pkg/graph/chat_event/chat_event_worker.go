package chat_event

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

type ChatEventWorker[T any] struct {
	waitCtx       context.Context
	waitCancel    context.CancelFunc
	ch            chan T
	batchSize     int
	buffSize      int
	totalCount    atomic.Int64
	consumerCount atomic.Int64
	doneCount     atomic.Int64
	errorCount    atomic.Int64
	producerDone  atomic.Bool

	// 完成通知机制
	completionOnce sync.Once
	completionCh   chan struct{}
}

type ChatEventWorkerResult struct {
	TotalCount    int64
	ConsumerCount int64
	DoneCount     int64
	ErrorCount    int64
}

func newChatEventWork[T any](buffSize int) *ChatEventWorker[T] {
	ctx, cancel := context.WithCancel(context.TODO())
	return &ChatEventWorker[T]{
		ch:           make(chan T, buffSize),
		batchSize:    1,
		buffSize:     buffSize,
		waitCtx:      ctx,
		waitCancel:   cancel,
		completionCh: make(chan struct{}),
	}
}

type ChatEventWorkerProducer[T any] struct {
	ctx    context.Context
	worker *ChatEventWorker[T]
}

func (p *ChatEventWorkerProducer[T]) Put(data T) error {
	logger := log.WithFields(p.ctx, map[string]interface{}{
		"func": "ChatEventWorkerProducer.Put",
	})

	defer func() {
		if r := recover(); r != nil {
			// 捕获了往已关闭channel写数据的panic
			logger.Warnf(p.ctx, "panic： %v", r)
		}
	}()

	select {
	case p.worker.ch <- data:
		p.worker.totalCount.Add(1)
		p.worker.checkCompletion()
		return nil
	case <-p.worker.waitCtx.Done():
		return fmt.Errorf("worker is stoped")
	}
}

func (w *ChatEventWorker[T]) checkCompletion() {
	if w.producerDone.Load() && w.consumerCount.Load() == w.totalCount.Load() {
		w.completionOnce.Do(func() {
			close(w.ch)
			w.waitCancel()
			close(w.completionCh)
		})
	}
}

func (w *ChatEventWorker[T]) Consumer(callback func(msg T) error) {
	logger := log.WithFields(w.waitCtx, map[string]interface{}{
		"func": "ChatEventWork.Consumer",
	})
	children := lo.ChannelDispatcher(w.ch, w.batchSize, w.buffSize, lo.DispatchingStrategyRoundRobin[T])
	consumer := func(c <-chan T) {
		defer func() {
			if r := recover(); r != nil {
				logger.Errorf(w.waitCtx, "panic: %v\n", r)
			}
		}()

		for {
			select {
			case msg, ok := <-c:
				if !ok {
					return
				}
				err := safe_group.SafeRun(func() error {
					return callback(msg)
				}, "chat-event-worker-consumer-callback")
				if err != nil {
					w.errorCount.Add(1)
					logger.Warnf(w.waitCtx, "callback error: %v\n", err)
				} else {
					w.doneCount.Add(1)
				}

				w.consumerCount.Add(1)
				w.checkCompletion()
			case <-w.waitCtx.Done():
				return
			}
		}
	}

	for i := range children {
		index := i
		safe_group.SafeGo(func() error {
			consumer(children[index])
			return nil
		}, "chat-event-worker-consumer")
	}
}

func (w *ChatEventWorker[T]) Producer(producerFunc func(producer *ChatEventWorkerProducer[T])) {
	producerFunc(&ChatEventWorkerProducer[T]{worker: w, ctx: w.waitCtx})
}

func (w *ChatEventWorker[T]) ProducerDone() {
	if w.producerDone.CompareAndSwap(false, true) {
		w.checkCompletion()
	}
}

func (w *ChatEventWorker[T]) IsProducerDone() bool {
	return w.producerDone.Load()
}

func (w *ChatEventWorker[T]) ProducerAndWait(producerFunc func(producer *ChatEventWorkerProducer[T])) {
	producerFunc(&ChatEventWorkerProducer[T]{worker: w, ctx: w.waitCtx})
	w.ProducerDone()
}

func (w *ChatEventWorker[T]) Wait() error {
	logger := log.WithFields(w.waitCtx, map[string]interface{}{
		"func": "ChatEventWork.Wait",
	})
	defer func() {
		if r := recover(); r != nil {
			// 捕获了往已关闭channel写数据的panic
			logger.Warnf(w.waitCtx, "panic: %v\n", r)
		}
	}()

	select {
	case <-w.completionCh:
		return nil
	case <-w.waitCtx.Done():
		return w.waitCtx.Err()
	}
}

func (w *ChatEventWorker[T]) Stop() {
	w.waitCancel()
}

func (w *ChatEventWorker[T]) GetResult() ChatEventWorkerResult {
	return ChatEventWorkerResult{
		TotalCount:    w.totalCount.Load(),
		ConsumerCount: w.consumerCount.Load(),
		DoneCount:     w.doneCount.Load(),
		ErrorCount:    w.errorCount.Load(),
	}
}
