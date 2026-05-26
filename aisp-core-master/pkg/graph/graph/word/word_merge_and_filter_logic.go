package word

import (
	"context"
	"fmt"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 词合并、过滤、去重

// WordMergeAndFilterLogic 词合并和过滤逻辑
type WordMergeAndFilterLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewWordMergeAndFilterLogic(name string, config map[string]string) *WordMergeAndFilterLogic {
	res := &WordMergeAndFilterLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.mergeWords
	return res
}

func (c *WordMergeAndFilterLogic) mergeWords(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordMergeAndFilterLogic.mergeWords")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "mergeWords",
	})
	logger.Debug(ctx, "do run mergeWords")

	if len(itemLists) == 0 {
		logger.Warn(ctx, "merge res is null")
		requestCtx.GetBizContext().SetResponseItemList([]*entities.Item{})
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 多路召回 扁平化处理
	flattenItems := lo.Flatten(itemLists)

	// 过滤字数为 maxWordLength 以内的词
	itemsFilter := lo.Filter(flattenItems, func(each *data_frame.ItemData[entities.Item], index int) bool {
		return len(each.GetBizItem().Text) > 0 && len(each.GetBizItem().QueryId) > 0 &&
			util.UnicodeWordLen(each.GetBizItem().Text) <= word.PrefabWordMaxLength
	})

	// 词去重
	itemsUniq := lo.UniqBy(itemsFilter, func(item *data_frame.ItemData[entities.Item]) string {
		return item.GetBizItem().Text
	})

	// 词总数打点
	c.statsdBySuccess(ctx, len(itemsUniq))

	var respList = make([]*data_frame.ItemData[entities.Item], 0)
	var itemRespList = make([]*entities.Item, 0)
	for _, v := range itemsUniq {
		itemRespList = append(itemRespList, v.GetBizItem())
		respList = append(respList, v)
	}
	requestCtx.GetBizContext().SetResponseItemList(itemRespList)
	return respList, nil
}

func (c *WordMergeAndFilterLogic) statsdBySuccess(ctx context.Context, num int) {
	statsdTmp := fmt.Sprintf("aisp-core.scene.%s.span.word.response.count",
		log.GetSceneFromContext(ctx))
	statsd.Count(statsdTmp, int64(num))
}
