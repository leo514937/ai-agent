package word

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/rum_cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/recall"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 预制词（随机）召回

// WordRandomGuideRecallLogic 预制词（随机）
type WordRandomGuideRecallLogic struct {
	*recall.DefaultRecaller[entities.RequestContext, entities.User, entities.Item]
	topK          int64
	prefabWordDao dao.PrefabWordV2Dao
	rumClient     rpc.RumClient[float32]
	rumCache      rum_cache.RumCache
}

func NewWordRandomGuideRecallLogic(name string, config map[string]string) *WordRandomGuideRecallLogic {
	res := &WordRandomGuideRecallLogic{
		DefaultRecaller: recall.NewDefaultRecaller[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	// 默认最多召回50个
	res.topK = 50
	res.prefabWordDao = impl.NewPrefabWordV2Dao()
	res.rumClient = rpcImpl.DefaultFloat32RumClientImpl
	res.rumCache = rum_cache.NewRumCache()
	res.RecallFunc = res.guideRandomWordRecall
	return res
}

func (l *WordRandomGuideRecallLogic) guideRandomWordRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordRandomGuideRecallLogic.guideRandomWordRecall")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	logger := log.WithField(ctx, "func", "guideRandomWordRecall")
	logger.Debug(ctx, "do running")

	words := l.prefabWordDao.GetRandomPrefabQueryV2ByRedis(ctx, l.topK, proto.QueryType_PREFAB_WORD_QUESTION)

	// 过滤删除词
	words = l.filterDeleteCache(ctx, words)

	// 返回词
	frameItem := make([]*data_frame.ItemData[entities.Item], 0)
	for _, query := range words {
		queryItem := entities.ItemFromQuery(query, -1, macro.CensorTypeMap[query.QueryType])
		frameItem = append(frameItem, queryItem.IntoFrameItem(requestCtx))
	}
	return frameItem, nil
}

// filterDeleteCache 后过滤被删除的缓存（异常删除rum 补偿）
func (l *WordRandomGuideRecallLogic) filterDeleteCache(ctx context.Context, words []*proto.Query) []*proto.Query {
	if len(words) == 0 {
		return words
	}

	logger := log.WithField(ctx, "func", "WordRandomGuideRecall-filterDeleteCache")

	var wordIds []int64
	var wordIdMap = make(map[int64]*proto.Query)

	for _, word := range words {
		wordIds = append(wordIds, cast.ToInt64(word.GetId()))
		wordIdMap[cast.ToInt64(word.GetId())] = word
	}

	availableIds := l.rumCache.FilterDeleteErrorWords(ctx, wordIds, macro.AiPrefabWordV2RumTable)

	finalWords := make([]*proto.Query, 0)
	for _, id := range availableIds {
		finalWords = append(finalWords, wordIdMap[id])
	}

	logger.Infof(ctx, "filter delete cache before size:%d after size:%d", len(words), len(finalWords))
	return finalWords
}
