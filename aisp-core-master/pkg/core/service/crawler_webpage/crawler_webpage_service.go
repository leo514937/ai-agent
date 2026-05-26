package crawler_webpage

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"strings"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

var containBlackList = []string{
	`www.medsci.cn/topic`,
	`www.medsci.cn/article`,
	`www.medsci.cn/guideline`,
	`www.medsci.cn/user`,
	`www.youlai.cn/yyk`,
	`www.medsci.cn/department`,
	`www.youlai.cn/ask/voicelist`,
	`www.youlai.cn/dise/imagedetail`,
	`www.youlai.cn/dise`,
	`www.familydoctor.com.cn/ask/doctor`,
	`www.youlai.cn/dise/videolist`,
	`www.familydoctor.com.cn/ask/hot`,
	`www.familydoctor.com.cn/baby/myk`,
	`www.youlai.cn/yyk/hospindex`,
	`www.familydoctor.com.cn/zhengxing/hot`,
	`www.medsci.cn/cn`,
	`www.familydoctor.com.cn/yinshi/sck`,
	`www.familydoctor.com.cn/error`,
	`www.youlai.cn/video`,
	`www.familydoctor.com.cn/ask/comment/q`,
	`www.medsci.cn/eda/subject`,
	`www.medsci.cn/eda/detail`,
	`www.medsci.cn/case`,
	`www.familydoctor.com.cn/ask/jbk`,
	`www.familydoctor.com.cn/buyunbuyu/by`,
	`www.youlai.cn/toutiao`,
	`www.medsci.cn/meeting`,
	`www.youlai.cn/kp`,
	`www.medsci.cn/form`,
	`www.dayi.org.cn/video_list`,
	`www.medsci.cn/link`,
	`www.familydoctor.com.cn/ask/did`,
	`www.medsci.cn/service`,
	`www.medsci.cn/live`,
	`www.youlai.cn/super`,
}

var regexBlackList = []string{
	`www.familydoctor.com.cn/.*/hot`,
}

const crawlerWebpageScene = "kafka.crawler"

type CrawlerWebpageService interface {
	IsUrlInBlackList(url string) bool
	UpsertDbAndIndex(ctx context.Context, item *module.CrawlerWebpageKafkaMsg) error
}

var DefaultCrawlerWebpageService CrawlerWebpageService

func init() {
	DefaultCrawlerWebpageService = NewCrawlerWebpageService()
}

type CrawlerWebpageServiceImpl struct {
	ruceneRpc            rpc.RuceneServiceRPC
	rumClient            rpc.RumClient[float32]
	klaraEmbeddingClient rpc.KlaraRpcClient
	klaraSparseClient    rpc.KlaraRpcClient
	crawlerWebPageDb     dao.CrawlerWebpageDao
}

func NewCrawlerWebpageService() *CrawlerWebpageServiceImpl {
	return &CrawlerWebpageServiceImpl{
		ruceneRpc:            rpc.DefaultRuceneServiceRPC,
		rumClient:            rpcImpl.DefaultFloat32RumClientImpl,
		klaraEmbeddingClient: rpcImpl.GetBgeEmbeddingClient("bge-m3-common-for-zhida"),
		klaraSparseClient:    rpcImpl.GetBgeEmbeddingClient("bge-m3-token"),
		crawlerWebPageDb:     impl.DefaultCrawlerWebpageDao,
	}
}

func (c *CrawlerWebpageServiceImpl) IsUrlInBlackList(url string) bool {
	for _, prefix := range containBlackList {
		if strings.Contains(url, prefix) {
			return true
		}
	}

	for _, regex := range regexBlackList {
		if matched, _ := regexp.MatchString(regex, url); matched {
			return true
		}
	}

	return false
}

func (c *CrawlerWebpageServiceImpl) UpsertDbAndIndex(ctx context.Context, item *module.CrawlerWebpageKafkaMsg) error {
	// 去除首尾空格换行
	item.Title = strings.TrimSpace(item.Title)
	item.Content = strings.TrimSpace(item.Content)

	// 过滤空内容
	if len(item.Title) == 0 || len(item.Content) == 0 {
		return nil
	}

	item.DocId = util.Hash64(item.MetaUrl)
	item.DocType = content.DocType_CrawlerWebpage

	err := c.upsertIntoDb(ctx, item)
	if err != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".db.count", crawlerWebpageScene))
		return err
	}

	// 构建 rucene 和 rum 索引
	ruceneErr := c.syncRucene(ctx, item)
	rumErr := c.syncRum(ctx, item)

	if ruceneErr != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".rucene.count", crawlerWebpageScene))
		return ruceneErr
	}

	if rumErr != nil {
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".rum.count", crawlerWebpageScene))
		return rumErr
	}

	return nil
}

func (c *CrawlerWebpageServiceImpl) syncRucene(ctx context.Context, input *module.CrawlerWebpageKafkaMsg) error {
	// title + content[:8192] 进行切词
	text := fmt.Sprintf("%s\n%s", input.Title, util.UnicodeSubstr(input.Content, 0, 8192))
	segmentWords := c.getSegment(ctx, text)

	if len(segmentWords) == 0 {
		return errors.New("get segment failed")
	}
	ruceneDoc := &model.CrawlerWebpageRucene{
		Id:          util.Int64String(input.DocId),
		DocId:       input.DocId,
		DocType:     input.DocType.String(),
		Domain:      input.Domain,
		Extra:       "",
		SparseScore: segmentWords,
	}

	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	return rpc.DefaultRuceneServiceRPC.Add(ctx, ruceneHost, model.CrawlerWebpagePath, model.CrawlerWebpageIndex, ruceneDoc, "")
}

func (c *CrawlerWebpageServiceImpl) getSegment(ctx context.Context, text string) []*model.SparseWord {
	var result []*model.SparseWord
	response := c.klaraSparseClient.BatchInferBgeM3Sparse(ctx, []string{text})
	if len(response) != 1 {
		return result
	}

	for _, word := range response[0] {
		if word.Weight > 0.05 {
			result = append(result, &model.SparseWord{
				Word:  word.Word,
				Score: word.Weight,
			})
		}
	}

	return result
}

func (c *CrawlerWebpageServiceImpl) syncRum(ctx context.Context, input *module.CrawlerWebpageKafkaMsg) error {
	// title + content[:8192] 计算 emb
	toEmbContent := fmt.Sprintf("%s\n%s", input.Title, util.UnicodeSubstr(input.Content, 0, 8192))

	embeddings := c.klaraEmbeddingClient.BatchInferBgeM3DenseEmb(ctx, []string{toEmbContent})
	if len(embeddings) != 1 {
		log.Errorf(ctx, "embedding result count is:%d", len(embeddings))
		return errors.New("get embedding failed")
	}

	resp := c.rumClient.RumUpsert(ctx, macro.CrawlerWebpageContentRumTable, input.DocId, embeddings[0], "", map[string]interface{}{
		macro.CrawlerWebpageDocIdFieldName:   input.DocId,
		macro.CrawlerWebpageDocTypeFieldName: input.DocType.String(),
		macro.CrawlerWebpageDomainFieldName:  input.Domain,
	})

	if resp == false {
		return errors.New("upsert rucene failed")
	}

	return nil
}

func (c *CrawlerWebpageServiceImpl) upsertIntoDb(ctx context.Context, input *module.CrawlerWebpageKafkaMsg) error {
	crawlerWebPage := &model.CrawlerWebPage{
		ObjectId:         input.ObjectId,
		DocId:            input.DocId,
		DocType:          input.DocType.String(),
		Title:            input.Title,
		MetaUrl:          input.MetaUrl,
		Source:           input.Source,
		Content:          input.Content,
		Domain:           input.Domain,
		PublishTime:      input.PublishTime,
		IsCrawlerAllowed: lo.Ternary(input.IsCrawlerAllowed, 1, 0),
		CrawlerTime:      input.CrawlerTime,
		ExtraInfo:        input.OtherInfo,
	}

	err := c.crawlerWebPageDb.BatchUpsert(ctx, []*model.CrawlerWebPage{crawlerWebPage})
	if err != nil {
		log.Errorf(ctx, "insert crawler webpage failed, error:%v", err)
		return err
	}

	return nil
}
