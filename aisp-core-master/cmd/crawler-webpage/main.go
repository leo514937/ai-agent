package crawler_webpage

import (
	"fmt"

	"git.apache.org/thrift.git/lib/go/thrift"
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/rpc"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/thrift_ai_tab"
)

func Main() {
	crawlerWebpageService := thrift_ai_tab.NewAispCrawlerWebpageService()

	// services
	servicesMap := map[string]thrift.TProcessor{
		"ContentService": content.NewContentServiceProcessor(crawlerWebpageService),
	}
	bundle := rpc.NewTZoneBundle(
		"aisp-crawler-webpage",
		rpc.WithTZoneServiceMap(servicesMap),
		rpc.TZoneListen(fmt.Sprintf("0.0.0.0:%d", 9999)),
	)
	app := cafe.NewApplication(cafe.SentryIncludePaths("git.in.zhihu.com/zhihu/aisp-core"))
	app.AddBundle(bundle)
	app.Run()
}
