package bundle

import (
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
)

// PrefabWordChangeProcessBundle 预制词更新
func PrefabWordChangeProcessBundle() cafe.Bundle {
	topicFuncMap := map[string]process.CommonKafkaProcess{
		string(macro.PrefabWord): process.NewPrefabWordChangeProcessor(),
	}

	return stream.NewStreamBundle("PrefabWordChangeStream",
		stream.WithSource(stream.NewKafkaSource([]string{string(macro.PrefabWord)})),
		stream.Concurrency(8),
		stream.WithProcessor(stream.FunctionProcessor(commonProcessBundleFunc(topicFuncMap))),
	)
}
