package rerank

import (
	"context"
	"sort"
	"strings"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank/rerank_sort"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

var beforeOtherKbSource conf.KbSource = "others"

// KbRecallChunkAndReRankV2BeforeLogic
// @logicAuthor: zhoupengcheng
// @logicInfo: 召回内容分块重排序 V2
type KbRecallChunkAndReRankV2BeforeLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	kbSourceOrder []conf.KbSource
}

func NewKbRecallChunkAndReRankV2BeforeLogic(name string, config map[string]string) *KbRecallChunkAndReRankV2BeforeLogic {
	res := &KbRecallChunkAndReRankV2BeforeLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.kbSourceOrder = []conf.KbSource{conf.KbSourceAuthorSelf, conf.KbSourceAuthorBge, conf.KbSourceZhihu}
	res.MergeFunc = res.realChunkAndReRank
	return res
}

func (s *KbRecallChunkAndReRankV2BeforeLogic) realChunkAndReRank(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallChunkReRankV2Logic realChunkAndReRank",
	})
	// 过滤chunk
	items := lo.Filter(lo.Flatten(itemLists), func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
	})
	if items == nil || len(items) == 0 {
		logger.Warn(ctx, "contents is nil or len(contents) == 0")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	items = entities.ItemListMergeDuplicate(items)
	contentTypeStrs := strings.Split(requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.Answer2CardContentType), ",")
	var contentTypes []content.DocType_Type

	for _, contentTypeStr := range contentTypeStrs {
		if code, exist := content.DocType_Type_value[contentTypeStr]; exist {
			contentTypes = append(contentTypes, content.DocType_Type(code))
		}
	}

	isEnableAuthorBgeStr := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.Answer2CardEnableAuthorBge)
	isEnableAuthorBge := cast.ToBool(isEnableAuthorBgeStr)

	respCache := make(map[string]int)
	// 该算子缓存 特殊处理 不作为缓存直接使用 而是辅助排序
	logicContext := logic_context.InitLogicContextV2[map[string]int](ctx, requestCtx, s.GetName(), "rerank.KbRecallChunkReRankV2Logic")
	ctx = logicContext.Ctx
	defer func() {
		logicContext.DeferFunc(&respCache)
	}()
	// 如果有缓存 则将缓存数据 放入到队列 用于辅助排序
	if logicContext.CacheResp.IsOk && logicContext.CacheResp.Resp != nil && len(logicContext.CacheResp.Resp) > 0 {
		for recallContentId, index := range logicContext.CacheResp.Resp {
			respCache[recallContentId] = index
		}
	}

	// 移除重复的创作者
	//items = s.removeSameAuthorDoc(items)

	isHit := false
	// 如果有缓存 则按照缓存序 进行排序
	if len(respCache) > 0 && len(items) == len(respCache) {
		isHit = true
		// 沿用上一次的序号
		for _, item := range items {
			orderNum, isOk := respCache[item.GetBizItem().GetItemRecallContentId()]
			if !isOk {
				isHit = false
				break
			}
			item.GetBizItem().OrderNumber = orderNum
		}
		if isHit {
			// 排序
			sort.Slice(items, func(i, j int) bool {
				return items[i].GetBizItem().OrderNumber < items[j].GetBizItem().OrderNumber
			})
		}
	}

	// 如果最终没命中缓存 则使用默认排序
	if !isHit {
		items = s.sortContentsBySource(s.kbSourceOrder, items)
	}

	// 最终处理脚标
	index := 0
	for _, item := range items {
		// 如果配置不可出 authorBge，则 KbSourceAuthorBge 来源的数据不允许吐出
		if !isEnableAuthorBge &&
			!lo.Contains(item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources, conf.KbSourceAuthorSelf) &&
			lo.Contains(item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources, conf.KbSourceAuthorBge) {
			item.GetBizItem().GetItemMeta().IsNotAllowSend = true
			continue
		}
		// 不是可以展示参考来源的内容类型，则不允许吐出
		if len(contentTypes) > 0 && !lo.Contains(contentTypes, item.GetBizItem().GetItemMeta().DocType) {
			item.GetBizItem().GetItemMeta().IsNotAllowSend = true
			continue
		}

		// 如果未命中缓存 需要新指定一下 order num
		if !isHit {
			item.GetBizItem().OrderNumber = index
			respCache[item.GetBizItem().GetItemRecallContentId()] = item.GetBizItem().OrderNumber
			index++
		}
		// 如果为创作者 则忽略脚标标识
		if lo.Contains(item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources, conf.KbSourceAuthorSelf) ||
			lo.Contains(item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources, conf.KbSourceAuthorBge) {
			continue
		}
		// IsPrepareCitable 是用来决定 前置是否有参与角标输出的条件
		// 该字段用于标识 是否预输出角标，最终是否输出角标由 chunkAndScore  used = true 来决定 IsCitable 是否为 true
		item.GetBizItem().GetItemMeta().GetRecallSourceInfo().IsPrepareCitable = true
	}

	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".rerank_before.length", float64(len(items)))

	return items, nil
}

// sortContextsBySource 排序
// 根据排序队列kbSourceOrder，对contexts按照原始顺序进行排序，其中属于other类型的，需要内部按照自己KbSource分组的下标位进行排序
// 如 self，答主, 知乎+Bing+其他（1,1,2,3,3,4,5）
// 有一个 kbSourceOrderArr 为 {"self", "cust"}
// 有一个 context为 [{"title":"测试1", "kbSource": "zhihu"}, {"title":"测试2", "kbSource": "bing"}, {"title":"测试3", "kbSource": "self"}, {"title":"测试4", "kbSource": "cust"}, {"title":"测试5", "kbSource": "cust"}, {"title":"测试6", "kbSource": "cust"}, {"title":"测试7", "kbSource": "zhihu"}, {"title":"测试8", "kbSource": "sougou"}, {"title":"测试9", "kbSource": "zhihu"}, {"title":"测试10", "kbSource": "bing"}]
// 1. 需要先按照 kbSourceOrderArr 的顺序排序，然后按照 kbSource 分组且不允许乱序，没有分到组的默认按照other为一组
// 2. others 组里的数据需要单独处理，再次按照自身的原始kbSource分组, 并最终排序为一个整体，例如：self，答主, 知乎+Bing+其他（1,1,2,3,3,4,5）
// 3. 最后吧所有的数据合并成一个数组返回
func (s *KbRecallChunkAndReRankV2BeforeLogic) sortContentsBySource(kbSourceOrderArr []conf.KbSource, contexts []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	if !lo.Contains(kbSourceOrderArr, beforeOtherKbSource) {
		kbSourceOrderArr = append(kbSourceOrderArr, beforeOtherKbSource)
	}

	groups := rerank_sort.SortGroup(beforeOtherKbSource, kbSourceOrderArr, contexts)
	newGroups := make(map[conf.KbSource][]*data_frame.ItemData[entities.Item])
	for source, recallItems := range groups {
		// 对recallItems 按照 kbSource  再次进行分组
		// 比如 第一次分组的 知乎内容，其实还包含了bing的召回源
		innerGroups := lo.GroupBy(recallItems, func(item *data_frame.ItemData[entities.Item]) conf.KbSource {
			for _, sourceTmp := range item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources {
				// 主要还是为了提取非source类型的数据
				if sourceTmp != source {
					return sourceTmp
				}
			}
			return source
		})

		// 获取到 otherGroups 组中最大的 length
		// 并对现有数据进行分桶
		bucket := make(map[conf.KbSource]map[int]*data_frame.ItemData[entities.Item])
		maxLength := 0
		for innerSource, innerRecallItems := range innerGroups {
			if len(innerRecallItems) > maxLength {
				maxLength = len(innerRecallItems)
			}
			for i, recallItem := range innerRecallItems {
				if _, existsMap := bucket[innerSource]; !existsMap {
					bucket[innerSource] = make(map[int]*data_frame.ItemData[entities.Item])
				}
				bucket[innerSource][i] = recallItem
			}
		}

		// 重新排序
		reRankArr := make([]*data_frame.ItemData[entities.Item], 0)
		for i := 0; i < maxLength; i++ {
			for innerSource := range innerGroups {
				recallItem, isExistRecallItem := bucket[innerSource][i]
				if isExistRecallItem {
					reRankArr = append(reRankArr, recallItem)
				}
			}
		}
		newGroups[source] = reRankArr
	}

	// 合并结果
	result := make([]*data_frame.ItemData[entities.Item], 0)

	// 首先添加 kbSourceOrderArr 中指定的组
	for _, source := range kbSourceOrderArr {
		if group, exists := newGroups[source]; exists {
			result = append(result, group...)
		}
	}
	return result
}

func (s *KbRecallChunkAndReRankV2BeforeLogic) removeSameAuthorDoc(items []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	var result []*data_frame.ItemData[entities.Item]
	authorMap := map[int64]bool{}
	for _, item := range items {
		itemMeta := item.GetBizItem().GetItemMeta()
		if (itemMeta.DocType == content.DocType_Answer || itemMeta.DocType == content.DocType_Article) &&
			itemMeta.ContentInfo != nil && itemMeta.ContentInfo.GetAuthorID() != 0 {
			if !authorMap[itemMeta.ContentInfo.GetAuthorID()] {
				result = append(result, item)
				authorMap[itemMeta.ContentInfo.GetAuthorID()] = true
			}
		} else {
			result = append(result, item)
		}
	}

	return result
}
