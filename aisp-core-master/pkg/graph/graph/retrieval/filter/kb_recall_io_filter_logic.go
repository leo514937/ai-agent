package filter

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

var allowDocType = []content.DocType_Type{content.DocType_Answer, content.DocType_Article}

// @logicAuthor: zhoupengcheng
// @logicInfo: 召回过滤

type KbRecallIoFilterLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewKbRecallIoFilterLogic(name string, config map[string]string) *KbRecallIoFilterLogic {
	res := &KbRecallIoFilterLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.realFilter
	return res
}

func (q *KbRecallIoFilterLogic) realFilter(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "recall.KbRecallIoFilterLogic.realFilter")
	defer span.Finish()

	isInside := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(q.GetName(), conf.SummaryRecallFilterIo.ToConvert()))

	logger := log.WithFields(ctx, map[string]any{
		"func":     "KbRecallIoFilterLogic realFilter",
		"isInside": isInside,
	})
	logger.Info(ctx, "do running")

	// 过滤站内外召回内容
	flattenList := lo.Flatten(itemLists)
	log.StatsdRecall(ctx, "is_inside_"+cast.ToString(isInside), "filter_flatten", len(flattenList))

	// item 去重
	uniqList := entities.ItemListMergeDuplicate(flattenList)

	log.StatsdRecall(ctx, "is_inside_"+cast.ToString(isInside), "filter_uniq", len(uniqList))

	// 根据站内外过滤item
	filterList := lo.Filter(uniqList, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return lo.Contains(allowDocType, item.GetBizItem().GetItemMeta().DocType) == isInside
	})
	log.StatsdRecall(ctx, "is_inside_"+cast.ToString(isInside), "filter_side", len(filterList))

	return filterList, nil
}
