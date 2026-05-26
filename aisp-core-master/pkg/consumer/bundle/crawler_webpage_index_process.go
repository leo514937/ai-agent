package bundle

import (
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
)

func CrawlerWebpageIndexProcessBundle() cafe.Bundle {
	topicFuncMap := map[string]process.CommonKafkaProcess{
		string(macro.CrawlerWebPage): process.NewCrawlerWebpageIndexProcessor(),
	}

	return stream.NewStreamBundle("CrawlerWebpageIndexStream",
		stream.WithSource(stream.NewKafkaSource([]string{string(macro.CrawlerWebPage)})),
		stream.Concurrency(10),
		stream.WithProcessor(stream.FunctionProcessor(commonProcessBundleFunc(topicFuncMap))),
	)
}
