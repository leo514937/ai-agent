package util

import (
	"context"
	"sync/atomic"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

// BatchWorker 定义一个结构体来存储共享数据和同步工具
// 使用方式
// 1. NewWork
// 2. Consumer
// 3. Producer
// 4. Wait
type BatchWorker[T any] struct {
	ctx           context.Context
	cancel        context.CancelFunc
	ch            chan T
	batchSize     int
	totalCount    int64
	consumerCount int64
	doneCount     int64
	producerDone  atomic.Bool
}

type BatchWorkerResult struct {
	TotalCount    int64
	ConsumerCount int64
	DoneCount     int64
	ErrorCount    int64
}

func NewWork[T any](batchSize int) *BatchWorker[T] {
	ctx, cancel := context.WithCancel(context.TODO())
	return &BatchWorker[T]{
		ch:        make(chan T, batchSize*batchSize),
		batchSize: batchSize,
		ctx:       ctx,
		cancel:    cancel,
	}
}

// BatchWorkerProducer 生产者
type BatchWorkerProducer[T any] struct {
	worker *BatchWorker[T]
}

// Put Producer 生产消息
func (p *BatchWorkerProducer[T]) Put(data T) {
	p.worker.ch <- data
	atomic.AddInt64(&p.worker.totalCount, 1)
}

// Consumer 消费者
func (w *BatchWorker[T]) Consumer(callback func(msg T) error) {
	logger := log.WithFields(w.ctx, map[string]interface{}{
		"func": "BatchWorker.Consumer",
	})
	// 使用 lo.ChannelDispatcher 分发通道
	children := lo.ChannelDispatcher(w.ch, w.batchSize, w.batchSize*2, lo.DispatchingStrategyRoundRobin[T])
	// 创建消费者
	consumer := func(c <-chan T) {
		for {
			msg, ok := <-c
			if !ok {
				logger.Infof(w.ctx, "closed")
				break
			}

			consumerErr := safe_group.SafeRun(func() error {
				return callback(msg)
			}, "batch-worker-consumer-callback")
			if consumerErr == nil {
				atomic.AddInt64(&w.doneCount, 1)
			} else {
				logger.Infof(w.ctx, "error: %v", consumerErr)
			}
			atomic.AddInt64(&w.consumerCount, 1)
		}
	}

	// 启动消费者
	for i := range children {
		index := i
		safe_group.SafeGo(func() error {
			consumer(children[index])
			return nil
		}, "batch-worker-consumer")
	}

	// consumer 执行完毕检测
	go func() {
		for {
			// 判断是否处理完成
			if w.producerDone.Load() && w.consumerCount == w.totalCount {
				close(w.ch)
				w.cancel()
				break
			}
		}
	}()
}

// Producer 生产者
// 因为生产者是非异步程序 会阻塞进程，在使用时放在 consumer 后面
func (w *BatchWorker[T]) Producer(producerFunc func(producer *BatchWorkerProducer[T])) {
	logger := log.WithFields(w.ctx, map[string]interface{}{
		"func": "BatchWorker.Producer",
	})
	producerErr := safe_group.SafeRun(func() error {
		producerFunc(&BatchWorkerProducer[T]{worker: w})
		return nil
	}, "batch-worker-consumer-callback")
	if producerErr != nil {
		logger.Infof(w.ctx, "error: %v", producerErr)
	}
	w.producerDone.CompareAndSwap(false, true)
}

// Wait 等待所有工作完成
func (w *BatchWorker[T]) Wait() {
	select {
	case <-w.ctx.Done():
		return
	}
}

// GetResult 获取执行结果
func (w *BatchWorker[T]) GetResult() BatchWorkerResult {
	return BatchWorkerResult{
		TotalCount:    w.totalCount,
		ConsumerCount: w.consumerCount,
		DoneCount:     w.doneCount,
		ErrorCount:    w.totalCount - w.doneCount,
	}
}
