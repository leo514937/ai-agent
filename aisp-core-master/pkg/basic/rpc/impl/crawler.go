package impl

import (
	"context"
	"errors"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/thrift-go/crawler_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type CrawlerThriftImpl struct {
	client *crawler_core_thrift.SpiderToolServiceClient
}

var DefaultCrawlerRpc rpc.CrawlerRpc

func init() {
	DefaultCrawlerRpc = NewCrawlerThriftImpl()
}

func NewCrawlerThriftImpl() *CrawlerThriftImpl {
	return &CrawlerThriftImpl{
		client: crawler_core_thrift.NewSpiderToolServiceClient(tzone.NewClient(
			"SpiderToolService",
			tzone.TargetName("crawler-rpc-service"),
			tzone.Timeout(60*time.Second))),
	}
}

func (s *CrawlerThriftImpl) RealTimeCrawler(ctx context.Context, url string) (*rpc.PageContent, error) {
	var resp *crawler_core_thrift.RealTimeCallback
	var err error
	runFunc := func(ctx context.Context) error {
		response, errTmp := s.client.RealTimeSpider(ctx, url)
		if errTmp != nil {
			log.WithError(ctx, errTmp).Errorf(ctx, "RealTimeCrawler failed. url=%s. err=%v", url, errTmp)
			err = errTmp
			return err
		} else {
			resp = response
			return nil
		}
	}

	// failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	err = runFunc(ctx)

	if err != nil {
		return nil, err
	}

	if resp == nil {
		return nil, errors.New("response is nil. url=" + url)
	}

	return &rpc.PageContent{
		Title:   resp.Title,
		Content: resp.HTMLContent,
	}, nil
}
