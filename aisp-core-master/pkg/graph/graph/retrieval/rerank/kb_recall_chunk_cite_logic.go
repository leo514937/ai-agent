package rerank

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// KbRecallChunkCiteBeforeLogic
// @logicAuthor: zhoupengcheng
// @logicInfo: 角标Before处理
type KbRecallChunkCiteBeforeLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	kbSourceOrder []conf.KbSource
}

func NewKbRecallChunkCiteBeforeLogic(name string, config map[string]string) *KbRecallChunkCiteBeforeLogic {
	res := &KbRecallChunkCiteBeforeLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.handleCite
	return res
}

func (s *KbRecallChunkCiteBeforeLogic) handleCite(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallChunkCiteBeforeLogic.handleCite",
	})
	// 过滤chunk
	items := lo.Filter(lo.Flatten(itemLists), func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
	})
	if items == nil || len(items) == 0 {
		logger.Warn(ctx, "contents is nil or len(contents) == 0")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 获取 过滤白名单配置
	filterIncludeDocTypeArr, filterIncludePaperArr := util.GetFilterIncludeTypeConfig(s.Name, requestCtx)

	span, ctx, _ := log.StartChildSpanWithContext(ctx, "retrieval.KbRecallChunkCiteBeforeLogic")
	defer span.Finish()
	span.LogFields(log.Message("start."))

	// 最终处理角标
	index := 0
	for _, item := range items {
		// 过滤白名单
		hitFilterWhiteList := item.GetBizItem().IsHitFilterWhiteList(filterIncludeDocTypeArr, filterIncludePaperArr)
		if !hitFilterWhiteList {
			item.GetBizItem().GetItemMeta().IsNotAllowSend = true
			continue
		}

		item.GetBizItem().OrderNumber = index
		// IsPrepareCitable 是用来决定 前置是否有参与角标输出的条件
		// 该字段用于标识 是否预输出角标，最终是否输出角标由 chunkAndScore  used = true 来决定 IsCitable 是否为 true
		item.GetBizItem().GetItemMeta().GetRecallSourceInfo().IsPrepareCitable = true
		index++
	}
	util2.TimingInMilSec(ctx, macro.CommonStatsPrefix+".rerank_before.length", float64(len(items)))
	return items, nil
}
