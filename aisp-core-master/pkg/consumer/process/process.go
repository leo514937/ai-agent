package process

import (
	"context"

	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
)

type CommonKafkaProcess interface {
	TopicName() macro.TopicName
	Process(ctx context.Context, message *stream.Message) error
}
