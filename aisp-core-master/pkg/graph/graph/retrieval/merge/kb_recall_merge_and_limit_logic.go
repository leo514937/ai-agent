package merge

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"

	//"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 召回内容合并截断
// @logicOutput: 0 | 召回结果。[]*data_frame.ItemData[entities.Item]
type recallResOrderGroup struct {
	orderGroup int
	items      []*entities.Item
}

type KbRecallMergeAndLimitLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewKbRecallMergeAndLimitLogic(name string, config map[string]string) *KbRecallMergeAndLimitLogic {
	res := &KbRecallMergeAndLimitLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.realMerge
	return res
}

func (i *KbRecallMergeAndLimitLogic) getRecallLimitConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) conf.RecallLimitConfig {
	logicConfigStr := requestCtx.GetBizContext().GetLogicConfig(i.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if logicConfigStr == "" {
		log.Errorf(ctx, "KbRecallMergeAndLimitLogic getConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), i.GetName()))
		return conf.RecallLimitConfig{}
	}
	recallLimitConfig := conf.RecallLimitConfig{}
	err := json.Unmarshal([]byte(logicConfigStr), &recallLimitConfig)
	if err != nil {
		log.Errorf(ctx, "KbRecallMergeAndLimitLogic getConfig error => %s", err)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), i.GetName()))
		return conf.RecallLimitConfig{}
	}
	return recallLimitConfig
}

func (i *KbRecallMergeAndLimitLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	var respItems = make([]*data_frame.ItemData[entities.Item], 0)

	span, ctx, logCtx, cacheRespInterface := logic_context.InitLogicContext(ctx, requestCtx, i.GetName(), "recall.KbRecallMergeLogic.realMerge")
	defer logic_context.DeferContext(span, i.GetName(), requestCtx, &respItems)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	if cacheRespInterface != nil {
		cacheResp, isTypeOk := cacheRespInterface.([]*data_frame.ItemData[entities.Item])
		if isTypeOk {
			return cacheResp, nil
		}
	}

	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallMergeLogic realMerge",
	})

	recallLimitConfig := i.getRecallLimitConfig(ctx, requestCtx)

	// 1. 拍平 Items
	recallItems := lo.Map(lo.Flatten(itemLists), func(item *data_frame.ItemData[entities.Item], index int) *entities.Item {
		return item.GetBizItem()
	})
	log.StatsdRecall(ctx, "chunk", "merge_flatten", len(recallItems))

	// 2. 取出知识库召回内容
	filterItems := lo.Filter(recallItems, func(item *entities.Item, index int) bool {
		return item.ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
	})
	log.StatsdRecall(ctx, "chunk", "merge_filter", len(filterItems))
	if filterItems == nil || len(filterItems) == 0 {
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	logger.Infof(ctx, "total number of recalled items => %d \n", len(filterItems))

	// 3. 取出一共有多少个召回源，并获取对应的数量限制
	kbSourceLimitTotal := 0
	kbSourceLimitMap := make(map[conf.KbSource]int)
	kbSourceCurrMap := make(map[conf.KbSource]int)
	for kbSourceStr, limitSize := range recallLimitConfig.RecallLimitMap {
		recallLimitSize := int(limitSize)
		kbSourceLimitTotal += recallLimitSize
		kbSourceLimitMap[kbSourceStr] = recallLimitSize
		kbSourceCurrMap[kbSourceStr] = 0
	}

	// 默认知识库召回
	// kbSourceLimitMap[conf.KbSourceZhihuKbEnhance] = 1
	logger.Infof(ctx, "recall limit => %s ", util.GetJSONIgnoreError(kbSourceLimitMap))
	logger.Infof(ctx, "recall limit total count => %d ", kbSourceLimitTotal)

	// 4. 分组后 按照 order group 排序,
	// 排序后的结果
	recallOrderSlice := make([]*recallResOrderGroup, 0)
	// 剩余Item 用于后期补足数据
	recallResidueMap := make(map[*entities.Item]*entities.Item)
	groupByRecallOrder := lo.GroupBy(filterItems, func(item *entities.Item) int {
		return item.GetItemMeta().GetRecallSourceInfo().OrderGroup
	})
	for orderGroup, items := range groupByRecallOrder {
		recallOrderSlice = append(recallOrderSlice, &recallResOrderGroup{orderGroup: orderGroup, items: items})
		for _, item := range items {
			recallResidueMap[item] = item
		}
	}
	sort.Slice(recallOrderSlice, func(i, j int) bool {
		return recallOrderSlice[i].orderGroup < recallOrderSlice[j].orderGroup
	})

	// 5. 分桶处理数据
	finalItems := make([]*entities.Item, 0)
	for _, slice := range recallOrderSlice {
		kbSource := slice.items[0].GetItemMeta().GetRecallSourceInfo().GetFirstKbSource()
		for _, item := range slice.items {
			if kbSourceCurrMap[kbSource] < kbSourceLimitMap[kbSource] {
				kbSourceCurrMap[kbSource]++
				finalItems = append(finalItems, item)
				delete(recallResidueMap, item)
			}
		}
	}
	// 6. 如果最终item < kbSourceLimitTotal 则补齐剩余内容
	if len(recallResidueMap) > 0 && len(finalItems) < kbSourceLimitTotal {
		logger.Warnf(ctx, " recall content is not enough and needs to be made up, count => %d", kbSourceLimitTotal-len(finalItems))
		for _, item := range recallResidueMap {
			if len(finalItems) >= kbSourceLimitTotal {
				break
			}
			finalItems = append(finalItems, item)
		}
	}

	// 7. 转换为 respItems
	respItems = lo.Map(finalItems, func(item *entities.Item, index int) *data_frame.ItemData[entities.Item] {
		return i.intoFrameItem(ctx, requestCtx, item)
	})

	logger.Infof(ctx, "recall curr limit => %s ", util.GetJSONIgnoreError(kbSourceCurrMap))
	logger.Infof(ctx, "total number of remaining recalled items: => %d ", len(respItems))

	// 记录打点信息
	i.saveFinalStatsd(ctx, finalItems, requestCtx)
	// 记录Tracing信息
	i.saveOriginalRecallTracing(logCtx, recallItems, respItems, requestCtx)

	// 继续透传召回结果
	return respItems, nil
}

func (i *KbRecallMergeAndLimitLogic) intoFrameItem(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	item *entities.Item) *data_frame.ItemData[entities.Item] {
	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallMergeLogic intoFrameItem",
	})
	logger.Debugf(ctx, "do running")

	// 3. 判断item是否展示
	//if lo.Contains(allowContentType, item.GetItemMeta().ContentType) {
	//	item.IsVisible = true
	//}
	return item.IntoFrameItem(requestCtx)
}

// saveFinalStatsd 保存打点信息
func (i *KbRecallMergeAndLimitLogic) saveFinalStatsd(
	ctx context.Context,
	finalItems []*entities.Item,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	// 打点 用于记录召回站外内容占知乎内容 独占比
	retrieval.SaveRecallZhihuMonopolyRatioStatsdByInnerItem(ctx, finalItems, "after")
	// 分组记录打点信息
	finalItemGroupByKbSource := lo.GroupBy(finalItems, func(item *entities.Item) string {
		return item.GetItemMeta().GetRecallSourceInfo().GetFirstKbSource().String()
	})
	// 打点用于记录 各个召回源最终喂给模型的数量
	for _, items := range finalItemGroupByKbSource {
		kbSource := items[0].GetItemMeta().GetRecallSourceInfo().GetFirstKbSource()
		log.StatsdRecall(ctx, "chunk", fmt.Sprintf("merge_limit.%s", kbSource.String()), len(items))
	}

	// 新
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".rerank.merge_rerank.length", float64(len(finalItems)))
	// 老
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank.merge_rerank.length", requestCtx.GetBizContext().Scenes()), float64(len(finalItems)))
	log.StatsdRecall(ctx, "chunk", "merge_resp", len(finalItems))
}

func (i *KbRecallMergeAndLimitLogic) saveOriginalRecallTracing(logCtx context.Context, recallItems []*entities.Item, finalItems []*data_frame.ItemData[entities.Item], requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	// 记录原始召回
	var recallIndexTracing []*proto.IndexTracing
	for _, item := range recallItems {
		recallIndexTracing = append(recallIndexTracing, i.item2IndexTracing(item))
	}
	requestCtx.GetBizContext().Tracing().ProcessTracing.OriginalRecallItem = recallIndexTracing

	// 记录最终合并
	var finalIndexTracing []*proto.IndexTracing
	for _, item := range finalItems {
		finalIndexTracing = append(finalIndexTracing, i.chunk2IndexTracing(item.GetBizItem()))
	}
	requestCtx.GetBizContext().Tracing().ProcessTracing.FinalIndex = finalIndexTracing

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(recallIndexTracing))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(finalIndexTracing))
}

func (i *KbRecallMergeAndLimitLogic) item2IndexTracing(item *entities.Item) *proto.IndexTracing {
	itemMeta := item.GetItemMeta()

	return &proto.IndexTracing{
		DocId:   itemMeta.DocId,
		DocType: util.DocType2ContentType(itemMeta.DocType),
		Title:   item.GetItemMeta().GetContentTitle(),
		Url:     itemMeta.Url,
		RecallInfo: []*proto.RecallInfo{{
			RecallSource: util.GetJSONIgnoreError(itemMeta.GetRecallSourceInfo()),
			RecallScore:  itemMeta.GetRecallSourceInfo().RecallScore,
			IsUsed:       true,
		}},
		PublishTime: item.ItemMeta.PublishedTime,
	}
}

func (i *KbRecallMergeAndLimitLogic) chunk2IndexTracing(item *entities.Item) *proto.IndexTracing {
	itemMeta := item.GetItemMeta()

	return &proto.IndexTracing{
		DocId:   itemMeta.DocId,
		DocType: util.DocType2ContentType(itemMeta.DocType),
		Text:    item.GetItemMeta().GetContentTitle(),
		Url:     itemMeta.Url,
		RecallInfo: []*proto.RecallInfo{{
			RecallSource: util.GetJSONIgnoreError(itemMeta.GetRecallSourceInfo()),
			RecallScore:  itemMeta.GetRecallSourceInfo().RecallScore,
			IsUsed:       true,
		}},
	}
}
