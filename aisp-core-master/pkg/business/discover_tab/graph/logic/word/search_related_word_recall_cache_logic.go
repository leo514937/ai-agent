package word

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

var statsRecallPrefix = macro.CommonStatsPrefix + ".word_recall_cache.%s.%s.count"

// @logicAuthor: zhoupengcheng
// @logicInfo: 搜索相关词 前置处理

// SearchRelatedWordRecallCacheLogic 相关词 拆解请求信息为知乎站内内容
type SearchRelatedWordRecallCacheLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	cacheDao dao.SearchRelatedWordRecallCacheDao
}

func NewSearchRelatedWordRecallCacheLogic(name string, config map[string]string) *SearchRelatedWordRecallCacheLogic {
	res := &SearchRelatedWordRecallCacheLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.cacheDao = daoImpl.NewSearchRelatedWordRecallCacheDao()
	res.MappingFunc = res.doHandle
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (l *SearchRelatedWordRecallCacheLogic) doHandle(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "word.SearchRelatedWordHandleLogic.doHandle")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))
	logger := log.WithField(ctx, "func", "SearchRelatedWordHandleLogic.doHandle")

	// 输出日志 记录 tracing
	resp := make([]*data_frame.ItemData[entities.Item], 0)

	// 1. 保存query 到 query merge 中， 用于处理后续召回逻辑
	queryMergeItem := l.genQueryMergeItem(requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent)
	requestCtx.GetBizContext().SetQueryMerge(queryMergeItem)

	// 2. 查询是否命中召回缓存 如果命中则不再走召回逻辑
	contentsByCache, _ := l.cacheDao.GetCache(ctx,
		requestCtx.GetBizContext().Scenes(),
		requestCtx.GetBizContext().MemberId(),
		requestCtx.GetBizContext().GetCurrentDialogue().Query.MessageContent)
	isHitCache := false
	if contentsByCache != nil && len(contentsByCache) > 0 {
		isHitCache = true
		for _, content := range contentsByCache {
			resp = append(resp, l.genRecallItem(content).IntoFrameItem(requestCtx))
		}
	}
	logger.Infof(ctx, "is hit recall cache => %v, itemsCount: %d", isHitCache, len(resp))
	requestCtx.DataMap().SetBool(logCtx, l.GetOutputName(0), isHitCache)
	return resp, nil
}

func (l *SearchRelatedWordRecallCacheLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "word.SearchRelatedWordRecallCacheLogic.chooseKey")
	defer span.Finish()
	span.LogFields(log.Message("SearchRelatedWordRecallCacheLogic chooseKey start."),
		log.Json("bizContext", param.RequestContext.GetBizContext()),
	)
	isHitCache, _ := param.RequestContext.DataMap().GetBool(logCtx, l.GetOutputName(0))

	resEdge := entities.MissCache
	if isHitCache {
		resEdge = entities.HitCache
	}
	// 打点
	util.Increment(ctx, statsRecallPrefix, param.RequestContext.GetBizContext().GetSuggestQueriesType().String(), resEdge)
	if isHitCache {
		span.LogFields(log.Message("SearchRelatedWordRecallCacheLogic chooseKey Break. Cache hit."))
		return entities.Break
	} else {
		span.LogFields(log.Message("SearchRelatedWordRecallCacheLogic chooseKey Normal. Cache not hit."))
		return entities.Normal
	}
}

func (l *SearchRelatedWordRecallCacheLogic) genQueryMergeItem(query string) *entities.Item {
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeQueryMerge,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 query,
		Security:             &model.Security{},
		ItemMeta:             &model.ItemMeta{},
	}
	return item
}

func (l *SearchRelatedWordRecallCacheLogic) genRecallItem(doc model.Content) *entities.Item {
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 "",
		ItemMeta: &model.ItemMeta{
			DocId:   doc.ContentID,
			DocType: doc.GetDocType(),
			Content: "",
			RecallSourceInfo: &model.RecallSourceInfo{
				RecallerName: l.GetName(),
				IndexSource:  conf.IndexSourceZhihu,
				IndexLevel:   conf.IndexLevel0,
				RecallScore:  0,
				OrderGroup:   0,
				KbSources:    []conf.KbSource{conf.KbSourceZhihu},
			},
		},
		Security: &model.Security{},
	}

	return item
}
