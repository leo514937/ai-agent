package word

import (
	"context"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/logic/word/word_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 相关词缓存（查询）

var statsPrefix = macro.CommonStatsPrefix + ".word_cache.%s.%s.count"

// GetRelatedWordCacheLogic 相关词缓存（查询）
type GetRelatedWordCacheLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	cacheDao           dao.RelatedWordCacheDao
	wordWrapperService word.WordMapperService
}

func NewGetRelatedWordCacheLogic(name string, config map[string]string) *GetRelatedWordCacheLogic {
	res := &GetRelatedWordCacheLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.cacheDao = daoImpl.NewRelatedWordCacheDao()
	res.wordWrapperService = word.NewWordMapperService()
	res.MappingFunc = res.getCache
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (l *GetRelatedWordCacheLogic) getCache(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "word.GetRelatedWordLogic.getCache")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	logger := log.WithField(ctx, "func", "GetRelatedWordCacheLogic")

	isUseCache := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.RelatedWordIsUseCache.ToConvert()))
	if !isUseCache {
		requestCtx.DataMap().SetBool(logCtx, l.GetOutputName(0), false)
		span.LogFields(log.Message("GetRelatedWordLogic.getCache Break. isUseCache is false."))
		return items, nil
	}

	var err error
	var cacheEItems []*entities.Item
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
		requestCtx.DataMap().SetBool(logCtx, l.GetOutputName(0), false)
		return items, nil
	}
	// 获取缓存
	cacheEItems, err = l.cacheDao.GetCache(ctx,
		requestCtx.GetBizContext().GetSuggestQueriesType().String(),
		cacheKey)

	if err != nil || len(cacheEItems) == 0 {
		requestCtx.DataMap().SetBool(logCtx, l.GetOutputName(0), false)
		return items, nil
	}

	resp := make([]*data_frame.ItemData[entities.Item], 0)

	syncMap := util.NewSyncMap[string, bool]()
	// 开启多线程查 当前缓存词是否已被处置
	wg := safe_group.NewGroupWithTimeout(fmt.Sprintf("%s_%s", l.GetName(), "GetRelatedWordCacheLogic-doCheckStatus"), 500)
	for _, eItem := range cacheEItems {
		eItemTmp := eItem
		wg.Go(func() error {
			wordId, wordErr := l.wordWrapperService.GetWordIdAndSaveWord(ctx, &model.WordMapperCreateDto{
				Word:     eItemTmp.Text,
				WordType: int32(eItemTmp.QueryType),
			})
			if wordId == 0 || wordErr != nil {
				return wordErr
			}
			syncMap.Set(eItemTmp.Text, true)
			return nil
		})
	}
	wgErr := wg.Wait()
	if wgErr != nil {
		logger.Warnf(ctx, "Wait Err => %v", wgErr)
	}

	// 验证缓存词是否已被处置
	for _, eItem := range cacheEItems {
		isAllowed, _ := syncMap.Get(eItem.Text)
		if isAllowed {
			resp = append(resp, eItem.IntoFrameItem(requestCtx))
		}
	}
	// 如果缓存的词 全部被处置完了 则需要重新生成
	if len(resp) == 0 {
		requestCtx.DataMap().SetBool(logCtx, l.GetOutputName(0), false)
		return items, nil
	}
	requestCtx.DataMap().SetBool(logCtx, l.GetOutputName(0), true)
	return resp, nil
}

func (l *GetRelatedWordCacheLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "word.GetRelatedWordLogic.chooseKey")
	defer span.Finish()
	span.LogFields(log.Message("GetRelatedWordLogic chooseKey start."),
		log.Json("bizContext", param.RequestContext.GetBizContext()),
	)

	isGenerate := cast.ToBool(param.RequestContext.GetBizContext().GetLogicConfig(l.GetName(), conf.RelatedWordCacheNilIsGenerate.ToConvert()))
	isHitCache, _ := param.RequestContext.DataMap().GetBool(logCtx, l.GetOutputName(0))

	resEdge := entities.MissCache
	if isHitCache {
		resEdge = entities.HitCache
	}
	// 打点
	util.Increment(ctx, statsPrefix, param.RequestContext.GetBizContext().GetSuggestQueriesType().String(), resEdge)

	if isHitCache {
		span.LogFields(log.Message("GetRelatedWordLogic chooseKey Break. Cache hit."))
		return entities.Break
	} else {
		span.LogFields(log.Message("GetRelatedWordLogic chooseKey Normal. Cache not hit."))
		if isGenerate {
			return entities.Normal
		}
		// 如果当前配置为 不继续生成 则直接break
		return entities.Break
	}
}
