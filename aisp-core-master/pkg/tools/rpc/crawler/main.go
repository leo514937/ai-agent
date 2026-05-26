package main

import (
	"context"
	"flag"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {
	url := flag.String("url", "", "url")
	flag.Parse()
	ctx := context.Background()
	res, err := impl.DefaultCrawlerRpc.RealTimeCrawler(ctx, *url)
	if err != nil {
		panic(err)
	}

	log.Infof(ctx, "title: %s, content: %s", res.Title, res.Content)
}
