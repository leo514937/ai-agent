package bundle

import (
	"context"

	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
)

func commonProcessBundleFunc(topicFunc map[string]process.CommonKafkaProcess) func(ctx context.Context, i interface{}) {
	return func(ctx context.Context, i interface{}) {
		msg := i.(stream.Message)
		var err error
		f, exist := topicFunc[msg.Topic]
		if !exist {
			return
		}
		err = f.Process(ctx, &msg)
		if err == nil {
			return
		}
	}
}
