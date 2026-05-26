package bundle

import (
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
)

// ContentActivityProcessBundle 追问相关词缓存更新
func ContentActivityProcessBundle() cafe.Bundle {
	topicFuncMap := map[string]process.CommonKafkaProcess{
		string(macro.ContentActivity): process.NewContentActivityProcessor(),
	}
	return stream.NewStreamBundle("ContentActivityStream",
		stream.WithSource(stream.NewKafkaSource([]string{string(macro.ContentActivity)})),
		stream.Concurrency(8),
		stream.WithProcessor(stream.FunctionProcessor(commonProcessBundleFunc(topicFuncMap))),
	)
}
