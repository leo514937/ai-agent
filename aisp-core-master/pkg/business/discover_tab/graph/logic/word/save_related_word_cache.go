package word

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/word/word_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 相关词缓存（保存）

// SaveRelatedWordCacheLogic 相关词缓存（保存）
type SaveRelatedWordCacheLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	cacheDao dao.RelatedWordCacheDao
	wordTTL  time.Duration
}

func NewSaveRelatedWordCacheLogic(name string, config map[string]string) *SaveRelatedWordCacheLogic {
	res := &SaveRelatedWordCacheLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.cacheDao = daoImpl.NewRelatedWordCacheDao()
	res.MappingFunc = res.saveCache
	return res
}

func (l *SaveRelatedWordCacheLogic) saveCache(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.SaveRelatedWordLogic.saveCache")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	logger := log.WithField(ctx, "func", "SaveRelatedWordLogic.saveCache")
	if items == nil || len(items) == 0 {
		log.Error(ctx, "SaveRelatedWordCacheLogic => items is nil")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 存储缓存
	eItems := lo.Map(items, func(item *data_frame.ItemData[entities.Item], index int) *entities.Item {
		return item.GetBizItem()
	})

	var saveCacheErr error
	var cacheKey dao.RelatedWordCacheKey
	if proto.SuggestQueriesType_ASK_AGAIN_RELATED == requestCtx.GetBizContext().GetSuggestQueriesType() {
		cacheKey = l.cacheDao.CreateAskCacheKey(
			model.NewContentWithDocType(
				requestCtx.GetBizContext().GetDocAboutQueriesRequest().GetDocId(),
				word_util.WordDocType2DocType(requestCtx.GetBizContext().GetDocAboutQueriesRequest().GetDocType()),
			))
	} else if proto.SuggestQueriesType_SEARCH_ASK_AGAIN_RELATED == requestCtx.GetBizContext().GetSuggestQueriesType() {
		cacheKey = l.cacheDao.CreateSearchAskCacheKey(
			requestCtx.GetBizContext().MemberId(),
			requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent)
	}
	if cacheKey == "" {
		return []*data_frame.ItemData[entities.Item]{}, nil
	}
	saveCacheErr = l.cacheDao.SaveCache(ctx,
		requestCtx.GetBizContext().GetSuggestQueriesType().String(),
		cacheKey,
		eItems)
	if saveCacheErr != nil {
		logger.Errorf(ctx, "save cache error => %v", saveCacheErr)
		return []*data_frame.ItemData[entities.Item]{}, saveCacheErr
	}
	return items, nil
}
