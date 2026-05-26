package rpc

import "context"

type CrawlerRpc interface {
	// RealTimeCrawler 调用爬虫，实时获取网页内容
	RealTimeCrawler(ctx context.Context, url string) (*PageContent, error)
}

type PageContent struct {
	Title   string
	Content string
}
