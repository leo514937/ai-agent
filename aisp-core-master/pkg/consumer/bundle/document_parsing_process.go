package bundle

import (
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
)

func DocumentParsingProcessBundle() cafe.Bundle {
	topicFuncMap := map[string]process.CommonKafkaProcess{
		string(macro.DocumentParsing): process.NewDocumentParsingProcessor(),
	}

	return stream.NewStreamBundle("DocumentParsingStream",
		stream.WithSource(stream.NewKafkaSource([]string{string(macro.DocumentParsing)})),
		stream.Concurrency(10),
		stream.WithProcessor(stream.FunctionProcessor(commonProcessBundleFunc(topicFuncMap))),
	)
}
