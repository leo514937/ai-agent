package operation_base

import (
	"context"
	"strings"
	"sync"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

type Faq struct {
	Question             string
	Answer               string
	QuestionNoSymbolHash int64
}

type OperationBaseService interface {
	// HitRedLineAnswer 是否命中红线必答，如果命中，返回答案
	HitRedLineAnswer(ctx context.Context, question string) (string, bool)
	// HitKnowledgeEnhance 是否命中知识增强，如果命中，返回要增强的内容
	HitKnowledgeEnhance(query string) (string, string, bool)
	// ListFaqs 返回和matchType匹配的所有faq内容
	ListFaqs(ctx context.Context, scene string, matchType conf.FaqMatchType) []*Faq

	refreshKnowledgeEnhance(ctx context.Context)
	refreshFaq(ctx context.Context)
}

type ServiceImpl struct {
	knowledgeBases map[string]string
	// key为场景
	faqBases map[string]map[conf.FaqMatchType][]*Faq

	knowledgeBaseDao dao.KnowledgeBaseV2DAO
	staticBaseDao    dao.StaticBaseDAO
	faqBaseDao       dao.FaqBaseDAO
}

func newOperationBaseService() *ServiceImpl {
	service := &ServiceImpl{
		knowledgeBases:   map[string]string{},
		knowledgeBaseDao: dao.DefaultKnowledgeBaseV2DAO,
		staticBaseDao:    dao.DefaultStaticBaseDAO,
		faqBaseDao:       dao.DefaultFaqBaseDAO,
	}

	ctx := context.Background()
	service.refreshKnowledgeEnhance(ctx)
	service.refreshFaq(ctx)
	return service
}

const keywordSplitter = ";"
const defaultBatchSize = 2000

var DefaultOperationBaseService OperationBaseService

func init() {
	DefaultOperationBaseService = newOperationBaseService()
	ticker := time.NewTicker(60 * 5 * time.Second)
	go startRefreshDaemon(ticker, DefaultOperationBaseService)
}

func (s *ServiceImpl) HitRedLineAnswer(ctx context.Context, question string) (string, bool) {
	questionHash := util.ConvertToRemovedSymbolHash(question)
	staticBases, err := s.staticBaseDao.ListOnlineByQuestionHash(ctx, questionHash)
	if err != nil {
		return "", false
	}

	// 防止hash冲突
	staticBases = lo.Filter(staticBases, func(item *model.StaticBase, _ int) bool {
		return util.RemoveSymbol(item.Question) == util.RemoveSymbol(question)
	})
	if len(staticBases) > 0 {
		return staticBases[0].Answer, true
	}
	return "", false
}

func (s *ServiceImpl) HitKnowledgeEnhance(query string) (string, string, bool) {
	for key, value := range s.knowledgeBases {
		if strings.Contains(query, key) {
			return value, key, true
		}
	}

	return "", "", false
}

func (s *ServiceImpl) ListFaqs(ctx context.Context, scene string, matchType conf.FaqMatchType) []*Faq {
	return s.faqBases[scene][matchType]
}

func startRefreshDaemon(ticker *time.Ticker, service OperationBaseService) {
	ctx := context.Background()
	mutex := sync.RWMutex{}
	for {
		select {
		case <-ticker.C:
			// update cache
			mutex.Lock() // lock the cache before writing into it
			service.refreshKnowledgeEnhance(ctx)
			service.refreshFaq(ctx)
			mutex.Unlock() // unlock the cache before writing into it
		}
	}
}

func (s *ServiceImpl) refreshKnowledgeEnhance(ctx context.Context) {
	emptyParams := &model.FilterParams{}
	totalCount, err := s.knowledgeBaseDao.GetTotalCount(ctx, emptyParams)
	if err != nil {
		return
	}
	batch := int(totalCount / defaultBatchSize)
	knowledgeBaseMap := map[string]string{}
	setValue := func(page int, size int) {
		params := &model.FilterParams{
			Page:     page,
			PageSize: defaultBatchSize,
		}

		knowledgeBases, err := s.knowledgeBaseDao.ListByParams(ctx, params)
		if err != nil {
			return
		}
		for _, knowledgeBase := range knowledgeBases {
			if knowledgeBase.StatusCode != model.OperationBaseStatusOnline {
				continue
			}
			keywords := strings.Split(knowledgeBase.KeyWords, keywordSplitter)
			for _, keyword := range keywords {
				knowledgeBaseMap[keyword] = knowledgeBase.KnowledgeContent
			}
		}
	}
	for i := 0; i < batch; i++ {
		setValue(i, defaultBatchSize)
	}
	setCount := batch * defaultBatchSize
	if setCount < int(totalCount) {
		setValue(batch, int(totalCount)-setCount)
	}
	s.knowledgeBases = knowledgeBaseMap
}

func (s *ServiceImpl) refreshFaq(ctx context.Context) {
	// batchSize这里需要设置大一点，防止created_at时间都是一致的，分页查询时出错
	batchSize := config.GetInt("operation_base.faq_batch_size", defaultBatchSize)
	begin := time.Now()
	log.Infof(ctx, "begin refresh faq.")

	emptyParams := &model.FilterParams{
		Status: model.OperationBaseStatusOnline,
	}
	totalCount, err := s.faqBaseDao.GetTotalCount(ctx, emptyParams)
	if err != nil {
		return
	}
	batch := int(totalCount) / batchSize
	faqMap := map[string]map[conf.FaqMatchType][]*Faq{}
	setValue := func(page int, size int) {
		params := &model.FilterParams{
			Page:     page,
			PageSize: batchSize,
			Status:   model.OperationBaseStatusOnline,
		}

		faqBases, err := s.faqBaseDao.ListByParams(ctx, params)
		if err != nil {
			log.WithError(ctx, err).Errorf(ctx, "faqBaseDao.ListByParams error. page=%d", page)
			return
		}
		for _, faq := range faqBases {
			for _, matchType := range conf.ConvertIntToFaqMatchTypeArray(faq.MatchType) {
				if _, ok := faqMap[faq.Scene]; !ok {
					faqMap[faq.Scene] = map[conf.FaqMatchType][]*Faq{}
				}
				faqMap[faq.Scene][matchType] = append(faqMap[faq.Scene][matchType], &Faq{
					Question:             faq.Question,
					Answer:               faq.Answer,
					QuestionNoSymbolHash: util.ConvertToRemovedSymbolHash(faq.Question),
				})
			}
		}
	}
	for i := 0; i < batch; i++ {
		setValue(i, batchSize)
	}
	setCount := batch * batchSize
	if setCount < int(totalCount) {
		setValue(batch, int(totalCount)-setCount)
	}
	s.faqBases = faqMap

	log.Infof(ctx, "refresh faq done. cost=%v", time.Since(begin))
}
