package rerank

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	util3 "git.in.zhihu.com/zrec/zrec-utils/util"
	"github.com/samber/lo"
)

// KbRecallChunkAndReRankV2AfterLogic
// @logicAuthor: zhoupengcheng
// @logicInfo: 召回内容分块重排序（喂给模型时 重排序） V2
type orderType int

const (
	authorSelf           orderType = 0
	timeliness           orderType = 1
	starAuthor           orderType = 2
	c4p                  orderType = 3
	internalQaTimeliness orderType = 4
	others               orderType = 5
)

type KbRecallChunkAndReRankV2AfterLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	orderList    []orderType
	orderFuncMap map[orderType]func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) bool
	sectionSize  int // 分段进行局部强插，例如 sectionSize=2 时，对于喂给模型参考的内容，截取分段前后50%，即0.5-1和0-0.5，分别进行 c4+ 等的强插，避免相关性过低的 c4+ 内容排到第一位
}

func NewKbRecallChunkAndReRankV2AfterLogic(name string, config map[string]string) *KbRecallChunkAndReRankV2AfterLogic {
	res := &KbRecallChunkAndReRankV2AfterLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.orderList = []orderType{authorSelf, timeliness, starAuthor, c4p, internalQaTimeliness, others}
	res.orderFuncMap = res.genOrderFuncMap()
	res.MergeFunc = res.realChunkAndReRank
	res.sectionSize = 5
	return res
}

func (s *KbRecallChunkAndReRankV2AfterLogic) genOrderFuncMap() map[orderType]func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) bool {
	return map[orderType]func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) bool{
		authorSelf: func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) bool {
			return lo.Contains(item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources, conf.KbSourceAuthorSelf)
		},
		timeliness: func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) bool {
			// queryMerge := requestCtx.GetBizContext().GetQueryMergeText()
			// todo: 待算法策略明确
			return false
		},
		starAuthor: func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) bool {
			_, exist := util2.GetStarAuthorIdNames()[item.GetBizItem().GetItemMeta().AuthorId]
			return exist
		},
		c4p: func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) bool {
			authorLevel := util2.GetCreatorDocLevelTagValue(item.GetBizItem().GetItemMeta().AuthorTagInfo)
			return authorLevel >= 4
		},
		// 内部问答-最近 6 个月内的内容优先
		internalQaTimeliness: func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) bool {
			if requestCtx.GetBizContext().RequestHeader().GetTrafficSource() == proto.TrafficSource_internal_qa {
				return util3.GetNowSecond()-item.GetBizItem().GetItemMeta().PublishedTime < 6*30*util3.DaySecond
			}
			return false
		},
		others: func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) bool {
			return true
		},
	}
}

func (s *KbRecallChunkAndReRankV2AfterLogic) realChunkAndReRank(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallChunkAndReRank2ModelV2Logic realChunkAndReRank",
	})
	// 过滤chunk
	items := lo.Filter(lo.Flatten(itemLists), func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
	})
	if items == nil || len(items) == 0 {
		logger.Warn(ctx, "contents is nil or len(contents) == 0")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	afterReRankItems := s.sort(requestCtx, items)
	usedCount := 0
	// 最终判断角标是否输出
	for _, item := range afterReRankItems {
		// 如果前面已经标记为预输出角标 则这里才会真正标记是否输出角标
		if item.GetBizItem().GetItemMeta().GetRecallSourceInfo().IsPrepareCitable {
			item.GetBizItem().IsCitable = true
			// 如果使用了重答 则还需要判断当前item 在重答范围内才可以置为开启
			if len(requestCtx.GetBizContext().GetRecallContentIds()) > 0 &&
				!lo.Contains(requestCtx.GetBizContext().GetRecallContentIds(), item.GetBizItem().GetItemRecallContentId()) {
				item.GetBizItem().IsCitable = false
			}
			// 以下为旧逻辑（当模型真正使用时 才会对要使用的召回内容出角标）
			//item.GetBizItem().IsCitable = item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used
		}
		if item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used {
			usedCount++
		}
	}
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".rerank_after.length", float64(usedCount))

	s.saveOriginalRecallTracing(ctx, afterReRankItems, requestCtx)
	return afterReRankItems, nil
}

// saveOriginalRecallTracing 保存 tracing 记录
func (s *KbRecallChunkAndReRankV2AfterLogic) saveOriginalRecallTracing(logCtx context.Context, finalItems []*data_frame.ItemData[entities.Item],
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {

	// 记录最终合并
	var finalIndexTracing []*proto.IndexTracing
	for _, item := range finalItems {
		finalIndexTracing = append(finalIndexTracing, s.chunk2IndexTracing(item.GetBizItem()))
	}
	requestCtx.GetBizContext().Tracing().ProcessTracing.FinalIndex = finalIndexTracing

	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(finalIndexTracing))
}

func (s *KbRecallChunkAndReRankV2AfterLogic) chunk2IndexTracing(item *entities.Item) *proto.IndexTracing {
	itemMeta := item.GetItemMeta()

	return &proto.IndexTracing{
		DocId:   itemMeta.DocId,
		DocType: util.DocType2ContentType(itemMeta.DocType),
		Text:    item.GetItemMeta().GetContentTitle(),
		Url:     itemMeta.Url,
		RecallInfo: []*proto.RecallInfo{{
			RecallSource: util.GetJSONIgnoreError(itemMeta.GetRecallSourceInfo()),
			RecallScore:  itemMeta.GetRecallSourceInfo().RecallScore,
			IsUsed:       itemMeta.GetRecallSourceInfo().Used,
		}},
	}
}

func (s *KbRecallChunkAndReRankV2AfterLogic) sort(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], contents []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	// 1.特殊逻辑：authorSelf 具有排他性，如果搜自己队列不为空，那么只填充 authorSelf 的内容
	authorSelfItems := s.getAuthorSelfItemList(requestCtx, contents)
	if len(authorSelfItems) > 0 {
		return authorSelfItems
	}

	// 2.区分模型使用和不使用，针对模型使用的部分，根据召回分数分段进行优先队列强插
	isUsedItemList := lo.GroupBy(contents, func(item *data_frame.ItemData[entities.Item]) bool {
		return item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used
	})
	usedItemList := isUsedItemList[true]

	// 根据召回分数分段
	scoreRanges := make([]float64, s.sectionSize+1)
	for i := 0; i <= s.sectionSize; i++ {
		scoreRanges[i] = 1.0 - float64(i)/float64(s.sectionSize)
	}

	// 将items按分数分组
	usedItemLists := make([][]*data_frame.ItemData[entities.Item], s.sectionSize)
	for _, item := range usedItemList {
		score := item.GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallScore
		for i := 0; i < s.sectionSize; i++ {
			if score <= scoreRanges[i] && score >= scoreRanges[i+1] {
				usedItemLists[i] = append(usedItemLists[i], item)
				break
			}
		}
	}

	for idx, items := range usedItemLists {
		usedItemLists[idx] = s.sortContentsByOrder(requestCtx, items)
	}
	unusedItemList := isUsedItemList[false]
	return append(lo.Flatten(usedItemLists), unusedItemList...)
}

func (s *KbRecallChunkAndReRankV2AfterLogic) getAuthorSelfItemList(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], contents []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	return lo.Filter(contents, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return s.orderFuncMap[authorSelf](requestCtx, item)
	})
}

// SortContentsByOrder 根据优先级进行重排序
func (s *KbRecallChunkAndReRankV2AfterLogic) sortContentsByOrder(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], contents []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	// 分组并保序
	groupList := make(map[orderType][]*data_frame.ItemData[entities.Item])
	for _, item := range contents {
		for _, order := range s.orderList {
			if s.orderFuncMap[order](requestCtx, item) {
				groupList[order] = append(groupList[order], item)
				break
			}
		}
	}

	// 合并
	resp := make([]*data_frame.ItemData[entities.Item], 0)
	for _, order := range s.orderList {
		resp = append(resp, groupList[order]...)
	}
	return resp
}
