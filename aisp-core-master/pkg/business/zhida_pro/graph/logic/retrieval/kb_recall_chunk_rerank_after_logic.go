package retrieval

import (
	"context"
	"sort"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank/rerank_sort"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

var afterOtherKbSource conf.KbSource = "other"

// KbRecallChunkAndReRankAfterLogic
// @logicAuthor: zhoupengcheng
// @logicInfo: 召回内容分块重排序（喂给模型时 重排序） V2
type KbRecallChunkAndReRankAfterLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	kbSourceOrder []conf.KbSource
}

func NewKbRecallChunkAndReRankAfterLogic(name string, config map[string]string) *KbRecallChunkAndReRankAfterLogic {
	res := &KbRecallChunkAndReRankAfterLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.kbSourceOrder = []conf.KbSource{}
	res.MergeFunc = res.realChunkAndReRank
	return res
}

func (s *KbRecallChunkAndReRankAfterLogic) realChunkAndReRank(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
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

	afterReRankItems := s.sortContentsByScore(requestCtx, s.kbSourceOrder, items)
	usedCount := 0
	// 最终判断角标是否输出
	for _, item := range afterReRankItems {
		// 如果前面已经标记为预输出角标 则这里才会真正标记是否输出角标
		if item.GetBizItem().GetItemMeta().GetRecallSourceInfo().IsPrepareCitable {
			item.GetBizItem().IsCitable = true
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
func (s *KbRecallChunkAndReRankAfterLogic) saveOriginalRecallTracing(logCtx context.Context, finalItems []*data_frame.ItemData[entities.Item],
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {

	// 记录最终合并
	var finalIndexTracing []*proto.IndexTracing
	for _, item := range finalItems {
		finalIndexTracing = append(finalIndexTracing, s.chunk2IndexTracing(item.GetBizItem()))
	}
	requestCtx.GetBizContext().Tracing().ProcessTracing.FinalIndex = finalIndexTracing

	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(finalIndexTracing))
}

func (s *KbRecallChunkAndReRankAfterLogic) chunk2IndexTracing(item *entities.Item) *proto.IndexTracing {
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

// SortContentsByScore 排序
// 根据排序队列kbSourceOrder，对contents按照Score大小顺序进行排序
func (s *KbRecallChunkAndReRankAfterLogic) sortContentsByScore(
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	kbSourceOrderArr []conf.KbSource,
	contents []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {

	if !lo.Contains(kbSourceOrderArr, afterOtherKbSource) {
		kbSourceOrderArr = append(kbSourceOrderArr, afterOtherKbSource)
	}

	// 按照指定召回源进行分组
	groupList := rerank_sort.SortGroup(afterOtherKbSource, kbSourceOrderArr, contents)

	// 如果配置只喂给模型 authorSelf，那么只取 KbSourceAuthorSelf 的内容
	isOnlyAuthorSelfStr := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.Answer2ModelOnlyAuthorSelf)
	isOnlyAuthorSelf := cast.ToBool(isOnlyAuthorSelfStr)
	if isOnlyAuthorSelf && len(groupList[conf.KbSourceAuthorSelf]) > 0 {
		return groupList[conf.KbSourceAuthorSelf]
	}

	// 对每个list 进行排序
	for _, itemList := range groupList {
		sort.Slice(itemList, func(i, j int) bool {
			return itemList[i].GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallScore > itemList[j].GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallScore
		})
	}

	// 合并
	resp := make([]*data_frame.ItemData[entities.Item], 0)
	for _, kbSource := range kbSourceOrderArr {
		resp = append(resp, groupList[kbSource]...)
	}
	return resp
}
