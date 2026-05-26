package bundle

import (
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
)

func DigitalAuthorIndexChangeProcessBundle() cafe.Bundle {
	topicFuncMap := map[string]process.CommonKafkaProcess{
		string(macro.DigitalAuthorIndexChange): process.NewDigitalAuthorIndexChangeProcessor(),
	}

	return stream.NewStreamBundle("DigitalAuthorIndexChangeStream",
		stream.WithSource(stream.NewKafkaSource([]string{string(macro.DigitalAuthorIndexChange)})),
		stream.Concurrency(1),
		stream.WithProcessor(stream.FunctionProcessor(commonProcessBundleFunc(topicFuncMap))),
	)
}
