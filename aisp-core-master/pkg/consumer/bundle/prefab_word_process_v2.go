package bundle

import (
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
)

// PrefabWordV2ChangeProcessBundle 预制词更新
func PrefabWordV2ChangeProcessBundle() cafe.Bundle {
	topicFuncMap := map[string]process.CommonKafkaProcess{
		string(macro.ContentPool): process.NewPrefabWordChangeV2Processor(),
	}

	return stream.NewStreamBundle("PrefabWordChangeV2Stream",
		stream.WithSource(stream.NewKafkaSource([]string{string(macro.ContentPool)})),
		stream.Concurrency(8),
		stream.WithProcessor(stream.FunctionProcessor(commonProcessBundleFunc(topicFuncMap))),
	)
}
