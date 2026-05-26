package process

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/core/crontab/zhida"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	util2 "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/cespare/xxhash/v2"
)

const outsiteScene = "kafka.outsite"

var SourceBlackList = []string{"快手", "抖音"}

type ZhidaOutSiteIndexProcessor struct {
	redisDao             dao.ZhidaOutSiteIndexDao
	ruceneRpc            rpc.RuceneServiceRPC
	rumClient            rpc.RumClient[float32]
	qpRpc                rpc.QueryProfileRpc
	klaraEmbeddingClient rpc.KlaraRpcClient
}

func NewZhidaOutSiteIndexProcessor() *ZhidaOutSiteIndexProcessor {
	return &ZhidaOutSiteIndexProcessor{
		redisDao:             impl.DefaultZhidaOutSiteIndexDaoImpl,
		ruceneRpc:            rpc.DefaultRuceneServiceRPC,
		rumClient:            rpcImpl.DefaultFloat32RumClientImpl,
		qpRpc:                rpcImpl.DefaultQpImpl,
		klaraEmbeddingClient: rpcImpl.GetBgeEmbeddingClient("ensemble_offline"),
	}
}

func (z *ZhidaOutSiteIndexProcessor) TopicName() macro.TopicName {
	return macro.HotCrawler
}

func (z *ZhidaOutSiteIndexProcessor) Process(ctx context.Context, message *stream.Message) error {
	msg := &module.HotCrawlerKafkaMsg{}
	err := json.Unmarshal(message.Value, msg)
	if err != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".unmarshal.count", outsiteScene))
		return errors.New("unmarshal error")
	}

	if util.IsMillisecond(msg.PublishTime) {
		msg.PublishTime = msg.PublishTime / 1000
	}

	// 对于热点内容，只要最近 30d 发布的
	if msg.PublishTime < util2.GetUnixTimestampToNow(0, 0, -30) {
		return nil
	}
	// 过滤黑名单来源
	if util.StringInSlice(msg.Source, SourceBlackList) {
		return nil
	}
	// 过滤不合法 url
	if !strings.HasPrefix(msg.LinkUrl, "http") {
		return nil
	}
	// 清洗 title
	title, err3 := util.ContentFilterHtml(ctx, msg.Title)
	if err3 != nil {
		title = msg.Title
	}
	// 清洗正文
	content := util.ContentFilterScripts(ctx, msg.Content)
	content, htmlFilterErr := util.ContentFilterHtml(ctx, content)
	if htmlFilterErr != nil {
		log.Errorf(ctx, "content filter error")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".html_filter.count", outsiteScene))
		return htmlFilterErr
	}
	// 去除首尾空格换行
	msg.Title = strings.TrimSpace(title)
	msg.Content = strings.TrimSpace(content)
	// 过滤空内容
	if len(msg.Content) == 0 {
		return nil
	}

	if !z.redisDao.GetItemUpdateLock(ctx, msg.LinkUrl, msg.Content) {
		util.Increment(ctx, macro.CommonStatsPrefix+".duplicate.count")
		return nil
	}

	// 构建 rucene 和 rum 索引
	ruceneErr := z.syncRucene(ctx, msg)
	rumErr := z.syncRum(ctx, msg)

	if ruceneErr != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".rucene.count", outsiteScene))
		return ruceneErr
	}

	if rumErr != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".rum.count", outsiteScene))
		return rumErr
	}

	util.Increment(ctx, macro.CommonStatsPrefix+".index_succ.count")
	return nil
}

func (z *ZhidaOutSiteIndexProcessor) syncRucene(ctx context.Context, input *module.HotCrawlerKafkaMsg) error {
	// title + content 进行切词
	text := fmt.Sprintf("%s\n%s", input.Title, input.Content)

	ruceneDoc := &model.ZhidaOutSiteRucene{
		Id:      util.Int64String(int64(xxhash.Sum64String(input.LinkUrl))),
		Title:   input.Title,
		Content: input.Content,
		ContentSeg: model.SegmentInfo{
			Words: z.getSegment(ctx, text),
			Raw:   input.Content,
			Store: true,
		},
		Domain:            input.Domain,
		BizType:           "热点",
		LinkUrl:           input.LinkUrl,
		Source:            input.Source,
		SourceType:        input.SourceType,
		PublishTimeSecond: input.PublishTime,
		UpsertTimeSecond:  time.Now().Unix(),
	}

	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	return rpc.DefaultRuceneServiceRPC.Add(ctx, ruceneHost, model.ZhidaOutSitePath, model.ZhidaOutSiteIndex, ruceneDoc, "")
}

func (z *ZhidaOutSiteIndexProcessor) getSegment(ctx context.Context, text string) []*model.Word {
	var result []*model.Word
	response := z.qpRpc.GetQueryProfile(ctx, text)
	if response == nil {
		return result
	}

	segWords := response.GetQueryProfile().GetSegmentInfo().GetWords()
	for _, item := range segWords {
		if item.GrainType == 1 {
			result = append(result, &model.Word{
				Value:  item.Word,
				Begin:  item.PositionBegin,
				Length: item.Length,
			})
		}
	}

	return result
}

func (z *ZhidaOutSiteIndexProcessor) syncRum(ctx context.Context, input *module.HotCrawlerKafkaMsg) error {
	// title + content[:512] 计算 emb
	toEmbContent := util.UnicodeSubstr(input.Content, 0, 512)
	toEmbContent = fmt.Sprintf("%s\n%s", input.Title, toEmbContent)

	embeddings := z.klaraEmbeddingClient.BatchInferEmbedding(ctx, []string{toEmbContent})
	if len(embeddings) != 1 {
		log.Errorf(ctx, "embedding result count is:%d", len(embeddings))
		return errors.New("get embedding failed")
	}

	id := int64(xxhash.Sum64String(input.LinkUrl))

	resp := z.rumClient.RumUpsert(ctx, macro.ZhidaOutSiteRumTable, id, embeddings[0], "", map[string]interface{}{
		macro.ZhidaOutSiteTitleFieldName:          input.Title,
		macro.ZhidaOutSiteContentFieldName:        input.Content,
		macro.ZhidaOutSiteLinkUrlFieldName:        input.LinkUrl,
		macro.ZhidaOutSiteLinkSourceFieldName:     input.Source,
		macro.ZhidaOutSiteLinkSourceTypeFieldName: input.SourceType,
		macro.ZhidaOutSiteBizTypeFieldName:        "热点",
		macro.ZhidaOutSiteDomainFieldName:         input.Domain,
		macro.ZhidaOutSitePublishTimeFieldName:    input.PublishTime,
	})

	if resp == false {
		return errors.New("upsert rucene failed")
	}

	return nil
}
