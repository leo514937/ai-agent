package process

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/core/crontab/zhida"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/crawler_webpage"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

const crawlerWebpageScene = "kafka.crawler"

type CrawlerWebpageIndexProcessor struct {
	crawlerWebpageService crawler_webpage.CrawlerWebpageService
}

func NewCrawlerWebpageIndexProcessor() *CrawlerWebpageIndexProcessor {
	return &CrawlerWebpageIndexProcessor{
		crawlerWebpageService: crawler_webpage.DefaultCrawlerWebpageService,
	}
}

func (c *CrawlerWebpageIndexProcessor) TopicName() macro.TopicName {
	return macro.CrawlerWebPage
}

func (c *CrawlerWebpageIndexProcessor) Process(ctx context.Context, message *stream.Message) error {
	msg := &module.CrawlerWebpageKafkaMsg{}
	err := json.Unmarshal(message.Value, msg)
	if err != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".unmarshal.count", crawlerWebpageScene))
		return errors.New("unmarshal error")
	}

	log.Infof(ctx, "receive crawler webpage message url:%s", msg.LinkUrl)

	if !strings.HasPrefix(msg.LinkUrl, "http") {
		return nil
	}

	if c.crawlerWebpageService.IsUrlInBlackList(msg.MetaUrl) {
		log.Infof(ctx, "url in black list, url:%s", msg.LinkUrl)
		return nil
	}

	err = c.crawlerWebpageService.UpsertDbAndIndex(ctx, msg)
	if err != nil {
		return err
	}

	log.Infof(ctx, "crawler webpage index success docId:%d, url:%s", msg.DocId, msg.LinkUrl)
	util.Increment(ctx, macro.CommonStatsPrefix+".index_succ.count")
	return nil
}
