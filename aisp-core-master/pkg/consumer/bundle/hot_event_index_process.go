package bundle

import (
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
)

func HotEventIndexProcessBundle() cafe.Bundle {
	topicFuncMap := map[string]process.CommonKafkaProcess{
		string(macro.HotEvent): process.NewHotEventIndexProcessor(),
	}

	return stream.NewStreamBundle("HotEventIndexStream",
		stream.WithSource(stream.NewKafkaSource([]string{string(macro.HotEvent)})),
		stream.Concurrency(10),
		stream.WithProcessor(stream.FunctionProcessor(commonProcessBundleFunc(topicFuncMap))),
	)
}
