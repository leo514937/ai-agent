package kafka

import (
	"context"
)

type Producer interface {
	SyncSend(ctx context.Context, msg *ProducerMessage) error
	AsyncSend(ctx context.Context, msg *ProducerMessage) error
	Input() chan<- *ProducerMessage
	Errors() <-chan *ProducerError
	Close() error
}

var GetProducer func(ctx context.Context, topic string) (Producer, error)

// ProducerMessage is the collection of elements passed to the Producer in order to send a message.
type ProducerMessage struct {
	// The partitioning key for this message. Pre-existing Encoders include
	// StringEncoder and ByteEncoder.
	Key []byte
	// The actual message to store in Kafka. Pre-existing Encoders include
	// StringEncoder and ByteEncoder.
	Value []byte
}

// ProducerError is the type of error generated when the producer fails to deliver a message.
// It contains the original ProducerMessage as well as the actual error value.
type ProducerError struct {
	Msg *ProducerMessage
	Err error
}
