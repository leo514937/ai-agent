package response

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 内容发送 Channel

type UploadRespChanLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
	chatMappingType entities.ChatMappingType
}

func NewUploadRespChanLogic(name string, config map[string]string) *UploadRespChanLogic {
	res := &UploadRespChanLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.uploadRespChan
	res.NeedSignal = false
	res.chatMappingType = entities.ChatMappingType(cast.ToInt64(config[conf.ConfigChatMappingType]))
	return res
}

func (u *UploadRespChanLogic) uploadRespChan(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "response.UploadRespChanLogic.uploadRespChan")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	// 避免空list，先做合并
	itemList := lo.Flatten(itemLists)

	u.ZagStatsD.RecordTime(requestCtx.GetCommonContext(), "respSize", int64(len(itemList)))
	if len(itemList) == 0 {
		u.ZagStatsD.Increment(requestCtx.GetCommonContext(), "empty")
	}

	// 上报数据
	u.uploadOutputData(ctx, itemList, requestCtx)
	// 记录tracing
	u.saveTracing(requestCtx, itemList)

	return itemList, nil
}

func (u *UploadRespChanLogic) saveTracing(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], itemList []*data_frame.ItemData[entities.Item]) {
	// 记录召回内容到 tracing
	if u.chatMappingType == entities.ChatMappingTypeRecallChunk {
		var displayOrder int32 = 1
		recallItemMap := map[string]*proto.RecallItems{}
		var recallItemCards []*proto.RecallItem

		for _, item := range itemList {
			recallItem := &proto.RecallItem{
				DocId:        item.GetBizItem().ItemMeta.DocId,
				DocType:      item.GetBizItem().ItemMeta.DocType.String(),
				Title:        item.GetBizItem().ItemMeta.GetTitle(),
				Url:          item.GetBizItem().ItemMeta.Url,
				Desc:         util.UnicodeSubstr(item.GetBizItem().GetItemMeta().Content, 0, 150),
				DisplayOrder: -1,
			}
			if isAllowSend(item.GetBizItem()) {
				recallItem.DisplayOrder = displayOrder
				displayOrder++
				recallItemCards = append(recallItemCards, recallItem)
			}
			source := item.GetBizItem().ItemMeta.GetRecallSourceInfo().GetFirstKbSource().String()

			if _, ok := recallItemMap[source]; !ok {
				recallItemMap[source] = &proto.RecallItems{
					Items: []*proto.RecallItem{},
				}
			}
			recallItemMap[source].Items = append(recallItemMap[source].Items, recallItem)
		}

		requestCtx.GetBizContext().GetMiddleProcess().Recalls = recallItemMap
		requestCtx.GetBizContext().GetMiddleProcess().Cards = recallItemCards
	}
}

func isAllowSend(item *entities.Item) bool {
	// 外链内容，还要检查 title 和 url 不为空
	if item.GetItemMeta().DocType == content.DocType_Link {
		return !item.GetItemMeta().IsNotAllowSend && item.GetItemMeta().Title != "" && item.GetItemMeta().Url != ""
	}
	// 其余内容
	return !item.GetItemMeta().IsNotAllowSend
}

func (u *UploadRespChanLogic) uploadOutputData(logCtx context.Context, items []*data_frame.ItemData[entities.Item],
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {

	// 记录召回 card
	if u.chatMappingType == entities.ChatMappingTypeRecallChunk {
		recallCardItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
			return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
		})
		bizType := requestCtx.GetBizContext().GetBizType()
		cards := make([]*proto.ChatCard, 0)
		for _, rItem := range recallCardItems {
			if bizType == proto.ChatType_ZHIDA_PRO_TAB.String() || bizType == proto.ChatType_ZHIDA_V2.String() || bizType == proto.ChatType_ZHIDA_AGENT.String() {
				cards = append(cards, rItem.GetBizItem().ToChatCardByZhiDa())
			} else if bizType == proto.ChatType_ZHIDA_MCP.String() {
				cards = append(cards, rItem.GetBizItem().ToChatCardByMCP())
			} else {
				cards = append(cards, rItem.GetBizItem().ToChatCard())
			}
		}
		requestCtx.GetBizContext().GetChatEvent().GetReferenceProducer().Send(cards).Done()
		requestCtx.DataMap().SetObjMap(logCtx, graph_macro.ZagKeyRecallItemsAfterMergeAndLimit, recallCardItems)
	} else if u.chatMappingType == entities.ChatMappingTypeQuestion {
		relateQueries := make([]*chat_event.RelateQueries, 0)
		for _, item := range items {
			query := item.GetBizItem().ToQuery()
			relateQueries = append(relateQueries, &chat_event.RelateQueries{
				QueryID:   query.GetId(),
				QueryType: query.GetQueryType(),
				QueryText: query.GetQuery(),
				RiskType:  query.GetRiskType(),
			})
		}
		requestCtx.GetBizContext().GetChatEvent().GetRelateQueriesProducer().Send(relateQueries).Done()
		requestCtx.DataMap().SetObjMap(logCtx, graph_macro.ZagKeyRelateQueries, items)
	}
}
