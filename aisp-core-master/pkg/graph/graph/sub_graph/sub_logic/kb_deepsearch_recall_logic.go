package sub_logic

import (
	"context"
	"net/url"
	"sort"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/req_macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/google/uuid"
	"github.com/samber/lo"
	"github.com/samber/lo/mutable"
)

// @logicAuthor: wangran
// @logicInfo: 直答 agent deepsearch 召回
type DeepSearchRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	qaGoRPC       rpc.QaGoRPC
	articleRPC    rpc.ArticleRPC
	recallService *sub_graph.RecallService
	aiIngressRPC  rpc.AiIngressRPC
	zFavRPC       rpc.ZFavRPC
}

func NewDeepSearchRecallLogic(name string, config map[string]string) *DeepSearchRecallLogic {
	res := &DeepSearchRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
		qaGoRPC:                  impl.DefaultQaGoRPCImpl,
		articleRPC:               impl.DefaultArticleRPCImpl,
		recallService:            sub_graph.NewRecallService(),
		aiIngressRPC:             impl.DefaultAiIngressRPCImpl,
		zFavRPC:                  impl.DefaultZFavRPCImpl,
	}

	res.RecallFunc = res.recall
	return res
}

func (d *DeepSearchRecallLogic) recall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	startTime := time.Now().UnixMilli()
	resList := make([]*data_frame.ItemData[entities.Item], 0)

	deepSearchContext := requestCtx.GetBizContext().GetDeepSearchContext()
	sourceMap := requestCtx.GetBizContext().GetSourceMap()
	if deepSearchContext == nil || sourceMap == nil {
		return resList, nil
	}

	// search or browse 召回
	if deepSearchContext.RetrievalType == proto.RetrievalType_RT_SEARCH {
		resList = d.searchRecall(ctx, requestCtx, deepSearchContext, sourceMap)
	} else if deepSearchContext.RetrievalType == proto.RetrievalType_RT_BROWSE {
		resList = d.browseRecall(ctx, requestCtx, deepSearchContext, sourceMap)
	}

	// 上一轮+本轮结果去重，重复时保留上一轮 item 实例
	resList = entities.ItemListMergeDuplicate(resList)
	resList = entities.ItemListDeduplicateWithPriority(deepSearchContext.LastRoundItems, resList)

	d.saveTracing(resList, startTime, requestCtx)
	return resList, nil
}

func (d *DeepSearchRecallLogic) browseRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], deepSearchContext *entities.DeepSearchContext,
	sourceMap map[string]*req_macro.SourceInfo) []*data_frame.ItemData[entities.Item] {

	result := make([]*data_frame.ItemData[entities.Item], 0)

	if len(deepSearchContext.SourcesName) == 0 {
		return result
	}

	for _, sourceName := range deepSearchContext.SourcesName {
		if !checkParam(sourceName, sourceMap) {
			continue
		}

		switch sourceMap[sourceName].Type {
		case req_macro.SourceTypePortfolio:
			result = append(result, d.GetPortfolioItems(ctx, requestCtx, sourceMap[sourceName].Meta.ID, deepSearchContext.Priority, sourceName)...)
		case req_macro.SourceTypeKnowledgeBase:
			result = append(result, d.GetKnowledgeBaseItems(ctx, requestCtx, sourceMap[sourceName].Meta.ID, sourceMap[sourceName].Meta.KnowledgeBaseType, getMemberId(requestCtx), sourceName, 20)...)
		case req_macro.SourceTypeSelected:
			result = append(result, []*data_frame.ItemData[entities.Item]{d.GetSelectItem(ctx, requestCtx, sourceMap[sourceName].Meta.ID, sourceMap[sourceName].Meta.DocType, "", sourceName)}...)
		}
	}

	return result
}

func (d *DeepSearchRecallLogic) searchRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], deepSearchContext *entities.DeepSearchContext,
	sourceMap map[string]*req_macro.SourceInfo) []*data_frame.ItemData[entities.Item] {

	result := make([]*data_frame.ItemData[entities.Item], 0)

	if len(deepSearchContext.Queries) == 0 || len(deepSearchContext.SourcesName) == 0 {
		return result
	}

	// 使用 safe_group 进行并发控制
	resultChan := make(chan []*data_frame.ItemData[entities.Item], len(deepSearchContext.Queries)*len(deepSearchContext.SourcesName))
	group := safe_group.NewGroupWithTimeout("DeepSearchRecallLogic", 10*1000).SetLimit(10) // 设置超时和并发限制

	// 启动 goroutines 处理每个 query 和 sourceName 的组合
	for _, query := range deepSearchContext.Queries {
		for _, sourceName := range deepSearchContext.SourcesName {
			group.Go(func() error {
				defer func() {
					if r := recover(); r != nil {
						log.Warnf(ctx, "DeepSearchRecallLogic Panic => %v", r)
					}
				}()

				var req *proto.ZhidaRecallRequest
				if !checkParam(sourceName, sourceMap) {
					return nil
				}
				switch sourceMap[sourceName].Type {
				case req_macro.SourceTypeIndex:
					req = d.genGeneralSearchRequest(requestCtx, query, sourceName, 5)
				case req_macro.SourceTypePortfolio:
					req = d.genAuthorSearchRequest(requestCtx, query, sourceMap[sourceName].Meta.ID, 5)
				case req_macro.SourceTypeKnowledgeBase:
					req = d.genKnowledgeBaseSearchRequest(requestCtx, query, sourceMap[sourceName].Meta.ID, sourceMap[sourceName].Meta.KnowledgeBaseType, 5)
				}
				if req == nil {
					return nil
				}
				respItems := d.GetRecallItems(ctx, requestCtx, req, query, "搜索索引:"+sourceName)

				select {
				case resultChan <- respItems:
					// 成功发送
				case <-ctx.Done():
					return ctx.Err()
				}
				return nil
			})
		}
	}

	// 等待所有 goroutine 完成后再关闭 channel
	go func() {
		if err := group.Wait(); err != nil {
			log.Warnf(ctx, "DeepSearchRecallLogic group Wait Err => %v", err)
		}
		close(resultChan)
	}()

	// 收集所有结果
	for respItems := range resultChan {
		result = append(result, respItems...)
	}

	return result
}

func checkParam(sourceName string, sourceMap map[string]*req_macro.SourceInfo) bool {
	if _, exist := sourceMap[sourceName]; !exist {
		return false
	}

	if sourceMap[sourceName].Type == req_macro.SourceTypePortfolio || sourceMap[sourceName].Type == req_macro.SourceTypeKnowledgeBase {
		if sourceMap[sourceName].Meta.ID == 0 {
			return false
		}
	}
	return true
}

func (d *DeepSearchRecallLogic) genGeneralSearchRequest(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], query string, sourceName string, limit int) *proto.ZhidaRecallRequest {
	return &proto.ZhidaRecallRequest{
		MemberId: getMemberId(requestCtx),
		Query:    query,
		Limit:    int32(limit),
		RecallExtInfo: &proto.RecallExtInfo{
			ChatType:        proto.ChatType_ZHIDA_V2,
			ClientSource:    proto.ClientSource_PC_WEB,
			TrafficSource:   proto.TrafficSource_zhida,
			MessageId:       getMessageId(requestCtx),
			RequestId:       util.Int64String(int64(uuid.New().ID())),
			ParentRequestId: getTraceId(requestCtx),
			Intention:       string(macro.GetQueryRouteSearch()),
			KnowledgeBases: []proto.KnowledgeBaseType{
				enums.KnowledgeBaseNameTypeMap[sourceName],
			},
		},
	}
}

func (d *DeepSearchRecallLogic) genAuthorSearchRequest(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], query string, authorId int64, limit int) *proto.ZhidaRecallRequest {
	return &proto.ZhidaRecallRequest{
		MemberId: getMemberId(requestCtx),
		Query:    query,
		Limit:    int32(limit),
		RecallExtInfo: &proto.RecallExtInfo{
			ChatType:        proto.ChatType_ZHIDA_V2,
			ClientSource:    proto.ClientSource_PC_WEB,
			TrafficSource:   proto.TrafficSource_zhida,
			MessageId:       getMessageId(requestCtx),
			RequestId:       util.Int64String(int64(uuid.New().ID())),
			ParentRequestId: getTraceId(requestCtx),
			Intention:       string(macro.GetQueryRouteSearch()),
			ReferenceMount: []*proto.ReferenceMount{
				{
					MountDoc: &proto.DocIdentity{
						DocId:   authorId,
						DocType: proto.DocType_MEMBER,
					},
				},
			},
		},
	}
}

func (d *DeepSearchRecallLogic) genKnowledgeBaseSearchRequest(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], query string, knowledgeBaseId int64, knowledgeBaseType proto.PersonalKnowledgeBaseType, limit int) *proto.ZhidaRecallRequest {
	return &proto.ZhidaRecallRequest{
		MemberId: getMemberId(requestCtx),
		Query:    query,
		Limit:    int32(limit),
		RecallExtInfo: &proto.RecallExtInfo{
			ChatType:        proto.ChatType_ZHIDA_V2,
			ClientSource:    proto.ClientSource_PC_WEB,
			TrafficSource:   proto.TrafficSource_zhida,
			MessageId:       getMessageId(requestCtx),
			RequestId:       util.Int64String(int64(uuid.New().ID())),
			ParentRequestId: getTraceId(requestCtx),
			Intention:       string(macro.GetQueryRouteSearch()),
			ReferenceMount: []*proto.ReferenceMount{
				{
					MountBase: &proto.PersonalKnowledgeBase{
						KnowledgeBaseId:   knowledgeBaseId,
						KnowledgeBaseType: knowledgeBaseType,
					},
				},
			},
		},
	}
}

func (d *DeepSearchRecallLogic) GetRecallItems(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	requestInfo *proto.ZhidaRecallRequest, query string, sourceName string) []*data_frame.ItemData[entities.Item] {
	var result []*data_frame.ItemData[entities.Item]
	itemList, err := d.recallService.Recall(ctx, requestInfo)
	if err != nil {
		log.Warnf(ctx, "DeepSearchRecallLogic GetZhidaRecall failed. error: %s", err.Error())
		return result
	}

	for _, item := range itemList {
		d.fillItem(item, query, sourceName)
		result = append(result, item.IntoFrameItem(requestCtx))
	}

	return result
}

func (d *DeepSearchRecallLogic) GetSelectItem(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	docId int64, docType content.DocType_Type, query string, sourceName string) *data_frame.ItemData[entities.Item] {

	sourceName = "用户选中:" + sourceName

	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 "",
		ItemMeta: &model.ItemMeta{
			DocId:   docId,
			DocType: docType,
			RecallSourceInfo: &model.RecallSourceInfo{
				KbSources: []conf.KbSource{conf.KbSourceMount},
			},
		},
		Security: &model.Security{},
	}
	d.fillItem(item, query, sourceName)
	return item.IntoFrameItem(requestCtx)
}

func (d *DeepSearchRecallLogic) GetPortfolioItems(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	authorId int64, priorityType entities.PriorityType, sourceName string) []*data_frame.ItemData[entities.Item] {

	var limit int64
	if priorityType == entities.PriorityTypeAll {
		limit = int64(config.GetInt(macro.BrowseAllLimit, 10))
	} else {
		limit = int64(config.GetInt(macro.BrowseRecentLimit, 10))
	}

	sourceName = "知乎创作:" + sourceName
	var answerIds, articleIds []int64

	if priorityType == entities.PriorityTypeRecency {
		answerIds = d.qaGoRPC.GetMemberCreateAnswerIds(ctx, authorId, rpc.OrderTypeTime, limit)
		articleIds = d.articleRPC.GetMemberCreateArticleIds(ctx, authorId, rpc.OrderTypeTime, limit)
	} else if priorityType == entities.PriorityTypeBest {
		answerIds = d.qaGoRPC.GetMemberCreateAnswerIds(ctx, authorId, rpc.OrderTypeHot, limit)
		articleIds = d.articleRPC.GetMemberCreateArticleIds(ctx, authorId, rpc.OrderTypeHot, limit)
	} else if priorityType == entities.PriorityTypeAll {
		recentAnswer := d.qaGoRPC.GetMemberCreateAnswerIds(ctx, authorId, rpc.OrderTypeTime, limit)
		hotAnswer := d.qaGoRPC.GetMemberCreateAnswerIds(ctx, authorId, rpc.OrderTypeHot, limit)
		answerIds = lo.Uniq(append(recentAnswer, hotAnswer...))

		recentArticle := d.articleRPC.GetMemberCreateArticleIds(ctx, authorId, rpc.OrderTypeTime, limit)
		hotArticle := d.articleRPC.GetMemberCreateArticleIds(ctx, authorId, rpc.OrderTypeHot, limit)
		articleIds = lo.Uniq(append(recentArticle, hotArticle...))
	} else {
		recentAnswer := d.qaGoRPC.GetMemberCreateAnswerIds(ctx, authorId, rpc.OrderTypeTime, limit)
		hotAnswer := d.qaGoRPC.GetMemberCreateAnswerIds(ctx, authorId, rpc.OrderTypeHot, limit)
		answerIds = lo.Uniq(append(recentAnswer, hotAnswer...))
		mutable.Shuffle(answerIds)

		recentArticle := d.articleRPC.GetMemberCreateArticleIds(ctx, authorId, rpc.OrderTypeTime, limit)
		hotArticle := d.articleRPC.GetMemberCreateArticleIds(ctx, authorId, rpc.OrderTypeHot, limit)
		articleIds = lo.Uniq(append(recentArticle, hotArticle...))
		mutable.Shuffle(articleIds)
	}

	var result []*data_frame.ItemData[entities.Item]
	for _, answerId := range answerIds {
		item := d.GetSelectItem(ctx, requestCtx, answerId, content.DocType_Answer, "", sourceName)
		result = append(result, item)
	}
	for _, articleId := range articleIds {
		item := d.GetSelectItem(ctx, requestCtx, articleId, content.DocType_Article, "", sourceName)
		result = append(result, item)
	}

	result = result[:lo.Min([]int{int(limit), len(result)})]
	return result
}

type KbItem struct {
	docId     int64
	docType   content.DocType_Type
	createdAt int64
}

func (d *DeepSearchRecallLogic) GetKnowledgeBaseItems(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	knowledgeBaseId int64, knowledgeBaseType proto.PersonalKnowledgeBaseType, memberId int64, sourceName string, limit int64) []*data_frame.ItemData[entities.Item] {

	sourceName = "知识库:" + sourceName

	if knowledgeBaseType == proto.PersonalKnowledgeBaseType_PKB_FOLDER || knowledgeBaseType == proto.PersonalKnowledgeBaseType_PKB_RSS {
		response := d.aiIngressRPC.GetKnowledgeBaseDetail(ctx, memberId, knowledgeBaseId, limit)
		if response == nil {
			return []*data_frame.ItemData[entities.Item]{}
		}
		KbItems := make([]*KbItem, 0)
		for _, kbItems := range response.GetKnowledgeItems() {
			docType := model.GetDocType(kbItems.GetType())
			for _, kbItem := range kbItems.GetItems() {
				docId := kbItem.GetID()
				createdAt := kbItem.GetCreatedAt()
				KbItems = append(KbItems, &KbItem{
					docId:     docId,
					docType:   docType,
					createdAt: createdAt,
				})
			}
		}
		// kbItems 按时间倒序排序
		sort.Slice(KbItems, func(i, j int) bool {
			return KbItems[i].createdAt > KbItems[j].createdAt
		})
		// 截取 limit 个
		KbItems = KbItems[:lo.Min([]int{len(KbItems), int(limit)})]
		var result []*data_frame.ItemData[entities.Item]
		for _, kbItem := range KbItems {
			item := d.GetSelectItem(ctx, requestCtx, kbItem.docId, kbItem.docType, "", sourceName)
			result = append(result, item)
		}
		return result
	}

	if knowledgeBaseType == proto.PersonalKnowledgeBaseType_PKB_FAV {
		favItemList := d.zFavRPC.ListFavlistItem(ctx, memberId, knowledgeBaseId)
		KbItems := make([]*KbItem, 0)
		for _, kbDoc := range favItemList {
			docType := rpc.ContentType2DocType(kbDoc.GetContentType())
			if docType == content.DocType_Unknown {
				continue
			}
			KbItems = append(KbItems, &KbItem{
				docId:     kbDoc.GetContentID(),
				docType:   docType,
				createdAt: kbDoc.GetCreated(),
			})
		}
		// kbItems 按时间倒序排序
		sort.Slice(KbItems, func(i, j int) bool {
			return KbItems[i].createdAt > KbItems[j].createdAt
		})
		// 截取 limit 个
		KbItems = KbItems[:lo.Min([]int{len(KbItems), int(limit)})]
		var result []*data_frame.ItemData[entities.Item]
		for _, kbItem := range KbItems {
			item := d.GetSelectItem(ctx, requestCtx, kbItem.docId, kbItem.docType, "", sourceName)
			result = append(result, item)
		}
		return result
	}

	return []*data_frame.ItemData[entities.Item]{}
}

func getMemberId(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) int64 {
	return requestContext.GetBizContext().MemberId()
}

func getMessageId(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	return requestContext.GetBizContext().MessageId()
}

func getTraceId(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	return requestContext.GetCommonContext().RequestId()
}

func (d *DeepSearchRecallLogic) fillItem(item *entities.Item, query string, sourceName string) *entities.Item {
	// 站外内容
	if item.GetItemMeta().IsOutLink() {
		// 设置 source
		sources := []string{"搜索索引:全网"}
		urlStr := item.GetItemMeta().Url
		if urlStr != "" {
			if parsedURL, err := url.Parse(urlStr); err == nil && parsedURL.Host != "" {
				sources = append(sources, "domain:"+parsedURL.Host)
			}
		}
		item.GetItemMeta().GetRecallSourceInfo().Source = sources
	} else {
		// 站内内容
		item.GetItemMeta().GetRecallSourceInfo().Source = []string{sourceName}
	}

	item.GetItemMeta().GetRecallSourceInfo().RecallQueryMerge = query

	return item
}

func (d *DeepSearchRecallLogic) saveTracing(outputItems []*data_frame.ItemData[entities.Item], startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:  d.GetName(),
		LogicInput: []string{},
		LogicOutput: lo.Map(outputItems, func(item *data_frame.ItemData[entities.Item], _ int) string {
			return item.GetBizItem().ToDescription()
		}),
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(d.GetName(), logicTracing)
}
