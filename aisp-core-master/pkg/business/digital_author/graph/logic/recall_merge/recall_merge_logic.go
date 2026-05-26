package recall_merge

import (
	"context"
	"fmt"
	"sort"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	digitalModel "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/similar"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type RecallMergeLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
	similarService service.SimilarService
	chunkSize      int
	chunkMaxSize   int
	chunkOverlap   int
	mergeLimit     int
	threshold      float64
}

func NewRecallMergeLogic(name string, config map[string]string) *RecallMergeLogic {
	res := &RecallMergeLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.similarService = service.NewSimilarService("ensemble")
	res.chunkSize = 1024
	res.chunkMaxSize = 1200
	res.chunkOverlap = 100
	res.mergeLimit = 3
	res.threshold = 0.55
	res.MergeFunc = res.buildResponse
	res.NeedSignal = true
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (r *RecallMergeLogic) buildResponse(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	logger := log.WithField(ctx, "respMessageId", requestCtx.GetBizContext().RespMessageId())

	span, ctx, _ := log.StartChildSpanWithContext(ctx, "recall_merge.RecallMergeLogic.buildResponse")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	var resultItem []*entities.Item
	var result []*data_frame.ItemData[entities.Item]

	// 遍历每个召回队列的结果，截取段落
	var chunkText []string
	var chunkItems []*entities.Item
	uniqueDocMap := map[string]bool{}

	for _, itemList := range itemLists {
		for _, item := range itemList {
			itemMeta := item.GetBizItem().GetItemMeta()
			// doc 去重
			if itemMeta.DocId != 0 && itemMeta.DocType != content.DocType_Unknown {
				uniqueKey := fmt.Sprintf("%d-%d", itemMeta.DocType, itemMeta.DocId)
				if uniqueDocMap[uniqueKey] {
					continue
				}
				uniqueDocMap[uniqueKey] = true
			}

			title := item.GetBizItem().GetItemMeta().Title
			text := item.GetBizItem().GetItemMeta().Content

			if title == "" && item.GetBizItem().GetItemMeta().ParentContentInfo != nil {
				title = item.GetBizItem().GetItemMeta().ParentContentInfo.GetTitle()
			}

			// 分块
			chunkList := util.SplitText([]rune(text), r.chunkSize, r.chunkMaxSize, r.chunkOverlap)

			for _, chunk := range chunkList {
				// 拼接 title 和 chunk 作为完整 chunk 内容
				chunk = fmt.Sprintf("%s\n%s", title, chunk)
				chunkText = append(chunkText, chunk)
				chunkItems = append(chunkItems, r.genChunkItem(ctx, chunk, item.GetBizItem()))
			}
		}
	}

	queryMerge := requestCtx.GetBizContext().GetQueryMerge().Text
	scores := r.similarService.BatchGetSimilarScore(ctx, queryMerge, chunkText)
	for j, score := range scores {
		chunkItems[j].ItemMeta.RankInfo = &model.RankInfo{SimilarScore: score}
	}

	// 倒排
	sort.Slice(chunkItems, func(i, j int) bool {
		return chunkItems[i].GetItemMeta().GetRankInfo().SimilarScore > chunkItems[j].GetItemMeta().GetRankInfo().SimilarScore
	})

	// 过滤低 score，并按照 level 聚合结果
	levelChunkItems := map[conf.IndexLevelType][]*entities.Item{}
	for _, chunkItem := range chunkItems {
		// 过滤 score
		if chunkItem.GetItemMeta().GetRankInfo().SimilarScore < r.threshold {
			continue
		}
		// 去除没有召回源的异常数据
		if chunkItem.GetItemMeta().RecallSourceInfo == nil {
			continue
		}
		// 限制长度
		indexLevel := chunkItem.GetItemMeta().RecallSourceInfo.IndexLevel
		if len(levelChunkItems[indexLevel]) >= r.mergeLimit {
			continue
		}

		levelChunkItems[indexLevel] = append(levelChunkItems[indexLevel], chunkItem)
	}

	logger.Infof(ctx, "recall result p0:%d, p1:%d, p2:%d", len(levelChunkItems[conf.IndexLevel0]), len(levelChunkItems[conf.IndexLevel1]), len(levelChunkItems[conf.IndexLevel2]))

	if len(levelChunkItems[conf.IndexLevel0]) > 0 {
		resultItem = levelChunkItems[conf.IndexLevel0]
	} else if len(levelChunkItems[conf.IndexLevel1]) > 0 {
		resultItem = levelChunkItems[conf.IndexLevel1]
	} else if len(levelChunkItems[conf.IndexLevel2]) > 0 {
		resultItem = levelChunkItems[conf.IndexLevel2]
	}

	r.saveRecallRecord(resultItem, requestCtx)
	r.saveFinalIndexTracing(resultItem, requestCtx)
	r.saveRecallIndexTracing(chunkItems, requestCtx)
	requestCtx.GetBizContext().SetRagRecallItems(resultItem)

	for i, item := range resultItem {
		item.OrderNumber = i
		item.IsCitable = true
		result = append(result, item.IntoFrameItem(requestCtx))
	}

	return result, nil
}

func (r *RecallMergeLogic) genChunkItem(ctx context.Context, chunkContent string, parentItem *entities.Item) *entities.Item {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "recall_merge.RecallMergeLogic.genChunkItem")
	defer span.Finish()

	itemMeta := &model.ItemMeta{}
	err := util.DeepCopyByJSON(itemMeta, parentItem.ItemMeta)
	if err != nil {
		log.Errorf(ctx, "RecallMergeLogic deep copy error. err:%v", err)
	}
	return &entities.Item{
		MessageId:            parentItem.MessageId,
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 chunkContent,
		ItemMeta:             itemMeta,
	}
}

func (r *RecallMergeLogic) saveRecallRecord(result []*entities.Item, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	digitalAuthorContext := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext)
	var recallKnowledge []*digitalModel.RecallKnowledge

	for _, item := range result {
		itemMeta := item.GetItemMeta()
		recallKnowledge = append(recallKnowledge, &digitalModel.RecallKnowledge{
			DocId:        itemMeta.DocId,
			DocType:      itemMeta.DocType.String(),
			RecallSource: digitalModel.IndexLevelSourceToBizType(itemMeta.GetRecallSourceInfo().IndexSource, itemMeta.GetRecallSourceInfo().IndexLevel),
			SimilarScore: itemMeta.GetRankInfo().SimilarScore,
			Text:         item.Text,
		})
	}

	digitalAuthorContext.SetRecallKnowledge(recallKnowledge)
}

func (r *RecallMergeLogic) saveRecallIndexTracing(items []*entities.Item, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	var indexTracing []*proto.IndexTracing
	for _, item := range items {
		indexTracing = append(indexTracing, r.item2IndexTracing(item))
	}
	requestCtx.GetBizContext().Tracing().ProcessTracing.RecallIndex = indexTracing
}

func (r *RecallMergeLogic) saveFinalIndexTracing(items []*entities.Item, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	var indexTracing []*proto.IndexTracing
	for _, item := range items {
		indexTracing = append(indexTracing, r.item2IndexTracing(item))
	}
	requestCtx.GetBizContext().Tracing().ProcessTracing.FinalIndex = indexTracing
}

func (r *RecallMergeLogic) item2IndexTracing(item *entities.Item) *proto.IndexTracing {
	itemMeta := item.GetItemMeta()

	return &proto.IndexTracing{
		DocId:   itemMeta.DocId,
		DocType: util.DocType2ContentType(itemMeta.DocType),
		Text:    item.Text,
		RecallInfo: []*proto.RecallInfo{{
			RecallSource: util.GetJSONIgnoreError(itemMeta.GetRecallSourceInfo()),
			RecallScore:  itemMeta.GetRecallSourceInfo().RecallScore,
		}},
		RankInfo: &proto.RankInfo{
			SimilarScore: itemMeta.GetRankInfo().SimilarScore,
		},
	}
}

func (r *RecallMergeLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "recall_merge.RecallMergeLogic.chooseKey")
	defer span.Finish()

	if len(param.RequestContext.GetBizContext().RagRecallItems()) > 0 {
		return entities.HasRetrieval
	} else {
		return entities.EmptyRetrieval
	}
}
