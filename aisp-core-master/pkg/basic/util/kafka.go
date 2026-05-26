package util

import (
	"context"
	"fmt"
	"io"
	"sync"
	"time"

	"git.in.zhihu.com/go/base/kafka"
	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/platform/sarama"
	jsoniter "github.com/json-iterator/go"
	"github.com/juju/ratelimit"
)

var ErrCreateProducerTooQuickly = fmt.Errorf("create producer too quickly")

const skipSandBoxForTopic = "data.aisp.common-tracing"

var (
	kafkaDiscovery      = kafka.NewDiscovery()
	Pek01KafkaDiscovery = func() kafka.Discovery {
		d := kafka.NewDiscovery()
		d.SkipSandBoxForTopic([]string{skipSandBoxForTopic})
		d.SetRegion("pek01")
		return d
	}
)
var (
	producerMap        sync.Map
	producerLimiterMap sync.Map
)

type KafkaProducerOption func(*sarama.Config)

func WithMaxMessageBytes(bytes int) KafkaProducerOption {
	return func(c *sarama.Config) {
		c.Producer.MaxMessageBytes = bytes
	}
}

func WithAck(ack sarama.RequiredAcks) KafkaProducerOption {
	return func(c *sarama.Config) {
		c.Producer.RequiredAcks = ack
	}
}

func NewKafkaProducer(ctx context.Context, topic string, discovery kafka.Discovery, opts ...KafkaProducerOption) (kafka.Producer, error) {
	logger := log.WithFields(ctx, log.Fields{
		"topic": topic,
	})

	options := kafka.DefaultProducerOptions()
	options.Producer.MaxMessageBytes = int(sarama.MaxRequestSize) - 1
	options.Producer.Compression = sarama.CompressionGZIP
	options.Metadata.RefreshFrequency = 10 * time.Second
	// Apply options
	for _, fun := range opts {
		fun(&options)
	}
	if discovery == nil {
		discovery = kafkaDiscovery
	}
	discovery.SkipSandBoxForTopic([]string{skipSandBoxForTopic})
	producer, err := discovery.ProducerWithOptions(ctx, topic, options)
	if err != nil {
		logger.WithError(err).Error("failed to create producer")

		return nil, err
	}
	utils.SafelyGo(func() {
		for err := range producer.Errors() {
			logger.WithError(err).Error("producer error")
		}
	}, nil)
	return producer, nil
}

func GetProducer(ctx context.Context, topic string) (kafka.Producer, error) {
	producer, _ := producerMap.Load(topic)
	if producer == nil {
		var limiter *ratelimit.Bucket
		if v, ok := producerLimiterMap.Load(topic); !ok {
			limiter = ratelimit.NewBucketWithRate(2, 200)
			producerLimiterMap.Store(topic, limiter)
		} else {
			limiter = v.(*ratelimit.Bucket)
		}

		if limiter.TakeAvailable(1) == 0 {
			return nil, ErrCreateProducerTooQuickly
		}

		logger := log.WithField(ctx, "topic", topic)
		logger.Info("create producer")
		var err error
		var producer kafka.Producer
		producer, err = NewKafkaProducer(ctx, topic, nil)
		if err != nil {
			logger.WithError(err).Error("failed to new producer")
			return nil, err
		}
		producerMap.Store(topic, producer)
		return producer, nil
	}
	return producer.(kafka.Producer), nil
}

func SendKafka(ctx context.Context, topic string, message interface{}) error {
	data, err := jsoniter.Marshal(message)
	if err != nil {
		return err
	}
	log.Infof(ctx, "send kafka msg start.  topic: %s data: %s", topic, string(data))

	producer, err := GetProducer(ctx, topic)
	if err != nil {
		return err
	}
	msg := &kafka.ProducerMessage{
		Topic: topic,
		Value: data,
	}
	return producer.AsyncSend(ctx, msg)
}

var (
// Kafka producers
// HistoryLogProducer             kafka.Producer
// UserObjectTagToOfflineProducer kafka.Producer
)

func init() {
	// 重定向sarama日志输出
	// sarama.Logger = logPkg.New(newSaramaLogger(), "[Sarama] ", 0)
	// 创建Producers
	// err := (error)(nil)
	// ctx := context.Background()

	// HistoryLogProducer, err = NewKafkaProducer(ctx, common.HistoryLogTopic, WithAck(sarama.NoResponse))
	// if err != nil {
	// 	panic(fmt.Errorf("failed to new producer for: %s", common.HistoryLogTopic))
	// }
	// UserObjectTagToOfflineProducer, err = NewKafkaProducer(ctx, common.UserObjectTagToOfflineTopic, WithAck(sarama.NoResponse))
	// if err != nil {
	// 	panic(fmt.Errorf("failed to new producer for: %s", common.UserObjectTagToOfflineTopic))
	// }
}

type saramaLogger struct {
}

func newSaramaLogger() io.Writer {
	return &saramaLogger{}
}

func (s *saramaLogger) Write(p []byte) (n int, err error) {
	num := len(p)
	if num > 0 {
		ctx, cancelFunc := context.WithTimeout(context.Background(), time.Second)
		defer cancelFunc()
		// 暂时将kafka运行过程中产生的日志记录到log.Warnf
		log.Warnf(ctx, string(p))

	}
	return num, nil
}
