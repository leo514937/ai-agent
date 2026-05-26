package kafka

import (
	"context"

	"git.in.zhihu.com/go/base/kafka"
	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

type ZhihuProducer struct {
	kafka.Producer

	input  chan *ProducerMessage
	errors chan *ProducerError
}

func (p *ZhihuProducer) SyncSend(ctx context.Context, msg *ProducerMessage) error {
	return p.Producer.SyncSend(ctx, producerMessageToBase(msg))
}

func (p *ZhihuProducer) AsyncSend(ctx context.Context, msg *ProducerMessage) error {
	return p.Producer.AsyncSend(ctx, producerMessageToBase(msg))
}

func (p *ZhihuProducer) Input() chan<- *ProducerMessage {
	return p.input
}

func (p *ZhihuProducer) Errors() <-chan *ProducerError {
	return p.errors
}

var _ Producer = (*ZhihuProducer)(nil)

func NewZhihuKafkaProducer(ctx context.Context, topic string) (*ZhihuProducer, error) {
	kafkaDiscovery := kafka.NewDiscovery()
	kafkaDiscovery.SkipSandBoxForTopic([]string{"data.aisp.common-tracing"})
	baseProducer, err := kafkaDiscovery.Producer(ctx, topic)
	if err != nil {
		return nil, err
	}
	p := &ZhihuProducer{
		Producer: baseProducer,
		input:    make(chan *ProducerMessage),
		errors:   make(chan *ProducerError),
	}
	utils.SafelyGo(func() {
		defer close(p.Producer.Input())
		for msg := range p.input {
			p.Producer.Input() <- producerMessageToBase(msg)
		}
	}, nil)
	utils.SafelyGo(func() {
		defer close(p.errors)
		for err := range p.Producer.Errors() {
			p.errors <- &ProducerError{
				Msg: &ProducerMessage{
					Key:   err.Msg.Key,
					Value: err.Msg.Value,
				},
				Err: err.Err,
			}
		}
	}, nil)
	utils.SafelyGo(func() {
		for err := range p.Errors() {
			log.WithFields(context.Background(), log.Fields{
				"err":   err,
				"topic": topic,
			}).Error("kafka producer error")
		}
	}, nil)
	return p, nil
}

func producerMessageToBase(msg *ProducerMessage) *kafka.ProducerMessage {
	return &kafka.ProducerMessage{
		Key:   msg.Key,
		Value: msg.Value,
	}
}

var producers = util.NewSyncMap[string, *ZhihuProducer]()

func init() {
	GetProducer = func(ctx context.Context, topic string) (Producer, error) {
		return producers.Emplace(topic, func() (*ZhihuProducer, error) {
			producer, err := NewZhihuKafkaProducer(ctx, topic)
			if err != nil {
				return nil, err
			}
			return producer, nil
		})
	}
}
