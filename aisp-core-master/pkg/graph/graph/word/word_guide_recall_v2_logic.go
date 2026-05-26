package word

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/rum_cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/recall"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"git.in.zhihu.com/zrec/zrec-utils/util"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 相关词召回V2

// WordGuideRecallV2Logic 预制词
type WordGuideRecallV2Logic struct {
	*recall.DefaultRecaller[entities.RequestContext, entities.User, entities.Item]
	topK               int32
	rumClient          rpc.RumClient[float32]
	rumCache           rum_cache.RumCache
	prefabWordCache    dao.PrefabWordV2Dao
	redisDao           dao.HotEventIndexDao
	wordWrapperService word.WordMapperService
}

func NewWordGuideRecallV2Logic(name string, config map[string]string) *WordGuideRecallV2Logic {
	res := &WordGuideRecallV2Logic{
		DefaultRecaller: recall.NewDefaultRecaller[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	// 默认最多召回50个
	res.topK = 50
	res.rumClient = rpcImpl.DefaultFloat32RumClientImpl
	res.rumCache = rum_cache.NewRumCache()
	res.prefabWordCache = daoImpl.NewPrefabWordV2Dao()
	res.redisDao = daoImpl.DefaultHotEventIndexDaoImpl
	res.wordWrapperService = word.NewWordMapperService()
	res.RecallFunc = res.guideWordRecall
	return res
}

func (l *WordGuideRecallV2Logic) guideWordRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordGuideRecallLogic.guideWordRecall")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	logger := log.WithField(ctx, "func", "guideWordRecallV2")
	logger.Debug(ctx, "do running")

	// 根据用户tag 查询 embeddings
	var tags = user.GetBizUser().UserMeta().GetTags()
	logger.Infof(ctx, "print member tag, memberId:%v, tags %v", requestCtx.GetBizContext().MemberId(), tags)

	embeddingModelName := requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.WordEmbeddingModelName.ToConvert())
	workTopKByStr := requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.WordTopK.ToConvert())
	wordTopK := cast.ToInt32(workTopKByStr)
	if wordTopK <= 0 {
		wordTopK = l.topK
	}

	// 获取 embedding
	embeddingRes := rpcImpl.GetBgeEmbeddingClient(embeddingModelName).BatchInferEmbedding(ctx, tags)
	if embeddingRes == nil || len(embeddingRes) == 0 {
		logger.Errorf(ctx, "embeddingRes length not equal to tags length")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 过滤掉空的embedding
	filterEmbeddingRes := lo.Filter(embeddingRes, func(item []float32, index int) bool {
		return item != nil && len(item) > 0
	})
	if filterEmbeddingRes == nil || len(filterEmbeddingRes) == 0 {
		logger.Warnf(ctx, "filterEmbeddingRes length not equal to tags length")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 从rum 表中获取引导词 与 去重
	questionRewriteArr := l.doSearchRumWord(ctx, int32(len(tags)*2), filterEmbeddingRes)

	unionByWords := lo.UniqBy(questionRewriteArr, func(item *proto.Query) string { return item.GetQuery() })

	// 后过滤 防止rum删除失败
	unionByWords = l.filterDeleteCache(ctx, unionByWords)

	// limit 限制词个数
	finalWords := unionByWords[:zrecUtil.Min(int(wordTopK), len(unionByWords))]
	if finalWords == nil || len(finalWords) == 0 {
		log.Error(ctx, "guide word recall empty")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 返回词
	frameItem := make([]*data_frame.ItemData[entities.Item], 0)
	for _, query := range finalWords {
		queryItem := entities.ItemFromQuery(query, -1, query.GetRiskType())
		queryItem.GetItemMeta().DocId = cast.ToInt64(query.GetId())
		queryItem.GetItemMeta().DocType = content.DocType_AiPrefabWord
		frameItem = append(frameItem, queryItem.IntoFrameItem(requestCtx))
	}
	return frameItem, nil
}

func (l *WordGuideRecallV2Logic) doSearchRumWord(ctx context.Context, rumLimit int32, embeddingRes [][]float32) []*proto.Query {
	if len(embeddingRes) == 0 {
		return []*proto.Query{}
	}

	logger := log.WithField(ctx, "func", "guideWordRecallV2-doSearchRumWord")

	// 开启多线程查根据 embedding 查 Rum
	wg := safe_group.NewGroupWithTimeout(fmt.Sprintf("%s_%s", l.GetName(), "guideWordRecall-doSearchRumWord"), 500)
	doneCh := make(chan int)
	resChan := make(chan []*model.PrefabWordInfo, len(embeddingRes))
	for _, embeddings := range util2.SplitSlice(embeddingRes, 10) {
		embeddings := embeddings
		// 查询 Rum
		wg.Go(func() error {
			words := make([]*model.PrefabWordInfo, 0)
			rumSearchRes := l.rumClient.RumSearch(ctx, macro.AiPrefabWordV3RumTable,
				embeddings, rumLimit, "", macro.PrefabWordFields)
			if rumSearchRes == nil || len(rumSearchRes) == 0 {
				return nil
			}
			itemList := lo.Flatten(rumSearchRes)
			for _, item := range itemList {
				rumItem, err := l.genRumItem(item)
				if err == nil {
					words = append(words, rumItem)
				}
			}
			// 使用select来判断channel是否关闭
			select {
			case <-doneCh:
				logger.Warnf(ctx, "Stop sending, channel is closed => %+v", words)
				return nil
			default:
				resChan <- words
			}
			return nil
		})
	}

	// 等待所有 goroutine 完成
	go func() {
		wgErr := wg.Wait()
		if wgErr != nil {
			logger.Warnf(ctx, "Wait Err => %v", wgErr)
		}
		close(doneCh)
		close(resChan)
	}()

	words := make([]*model.PrefabWordInfo, 0)
	for res := range resChan {
		words = append(words, res...)
	}

	var finalWords []*model.PrefabWordInfo

	for _, word := range words {
		// 非热点事件引导词不进行时效性过滤，直接放到结果里
		if word.QueryType != proto.QueryType_RELATE_WORD_HOT_EVENT {
			finalWords = append(finalWords, word)
			continue
		}
		// 热点事件引导词：短时效当前日期-入池日期<7d，中时效当前日期-入池日期<14d
		publishTime, timeliness := l.redisDao.GetWordCreateTimeAndTimeliness(ctx, word.WordId)
		if timeliness == macro.TimelinessShort && util.GetNowSecond()-publishTime < 7*util.DaySecond {
			finalWords = append(finalWords, word)
		} else if timeliness == macro.TimelinessMiddle && util.GetNowSecond()-publishTime < 14*util.DaySecond {
			finalWords = append(finalWords, word)
		} else {
			// 异步进行删除操作
			safe_group.SafeGo(func() error {
				return l.delWord(ctx, word.WordId, word.QueryType)
			}, "del_word")
		}
	}

	return l.prefabWordCache.HandleToConvertQueryV2(finalWords)
}

func (l *WordGuideRecallV2Logic) delWord(ctx context.Context, wordId int64, queryType proto.QueryType) error {
	newCtx, cancel := context.WithTimeout(util2.WithoutCancel(ctx), 2*time.Second)
	defer cancel()

	// 删除 rum
	l.rumClient.RumDelete(newCtx, macro.AiPrefabWordV3RumTable, wordId, "")
	// 删除 MySQL
	_, deleteMySQLErr := l.wordWrapperService.RemoveWordId(newCtx, wordId, int32(queryType))
	return deleteMySQLErr
}

func (l *WordGuideRecallV2Logic) genRumItem(rumItem *rpc.SearchResult) (*model.PrefabWordInfo, error) {
	wordId := rumItem.GetId()
	queryType := proto.QueryType(util.InterfaceTryGetInt64(rumItem.Fields[macro.PrefabWordQueryTypeFieldName], 0))
	extraInfoStr := util.InterfaceTryGetString(rumItem.Fields[macro.PrefabWordRawFieldName], "")

	extraInfo := &model.PrefabWordExtraInfo{}
	err := json.Unmarshal([]byte(extraInfoStr), extraInfo)
	if err != nil {
		return nil, err
	}

	return &model.PrefabWordInfo{
		WordId:    wordId,
		Word:      extraInfo.GetWord(),
		QueryType: queryType,
		ExtraInfo: extraInfo,
	}, nil
}

// filterDeleteCache 后过滤被删除的缓存（异常删除rum 补偿）
func (l *WordGuideRecallV2Logic) filterDeleteCache(ctx context.Context, words []*proto.Query) []*proto.Query {
	if len(words) == 0 {
		return words
	}

	logger := log.WithField(ctx, "func", "guideWordRecallV2-filterDeleteCache")

	var wordIds []int64
	var wordIdMap = make(map[int64]*proto.Query)

	for _, word := range words {
		wordIds = append(wordIds, cast.ToInt64(word.GetId()))
		wordIdMap[cast.ToInt64(word.GetId())] = word
	}

	availableIds := l.rumCache.FilterDeleteErrorWords(ctx, wordIds, macro.AiPrefabWordV3RumTable)

	finalWords := make([]*proto.Query, 0)
	for _, id := range availableIds {
		finalWords = append(finalWords, wordIdMap[id])
	}

	logger.Infof(ctx, "filter delete cache before size:%d after size:%d", len(words), len(finalWords))
	return finalWords
}
