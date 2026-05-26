package retrieval

import (
	"context"
	"fmt"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

type TextPart lo.Tuple3[string, *base.ContentInfo, float64]

// RecallTextAndScore 召回文本和分数
type RecallTextAndScore struct {
	Text  string
	Score float64
	Item  *data_frame.ItemData[entities.Item]
}

// =============

func SaveRecallZhihuMonopolyRatioStatsd(ctx context.Context, items []*data_frame.ItemData[entities.Item], stage string) {
	innerItems := make([]*entities.Item, 0)
	for _, item := range items {
		innerItems = append(innerItems, item.GetBizItem())
	}
	SaveRecallZhihuMonopolyRatioStatsdByInnerItem(ctx, innerItems, stage)
}

func SaveRecallZhihuMonopolyRatioStatsdByInnerItem(ctx context.Context, items []*entities.Item, stage string) {
	// 过滤数据
	filterItems := lo.Filter(items, func(item *entities.Item, _ int) bool {
		return item.ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk && item.GetItemMeta().DocType != content.DocType_Unknown
	})
	if filterItems == nil || len(filterItems) == 0 {
		return
	}

	// 按照召回源分组
	groupBySource := make(map[conf.KbSource][]*entities.Item)
	for _, item := range filterItems {
		for _, source := range item.GetItemMeta().GetRecallSourceInfo().KbSources {
			groupBySource[source] = append(groupBySource[source], item)
		}
	}

	scene := log.GetSceneFromContext(ctx)
	for source, sourceItems := range groupBySource {
		// 独占数
		monopolyNum := 0
		for _, itemTmp := range sourceItems {
			if len(itemTmp.GetItemMeta().GetRecallSourceInfo().KbSources) == 1 {
				monopolyNum += 1
			}
		}
		sourceDocIds := lo.Map(sourceItems, func(item *entities.Item, _ int) string {
			return item.GetItemMeta().GenItemKey()
		})

		differenceBucket := fmt.Sprintf("aisp-core.scene.%s.recall.zhihu_monopoly_ratio.stage.%s.source.%s.op.difference",
			scene, stage, source.String())
		differenceAllBucket := fmt.Sprintf("aisp-core.scene.%s.recall.zhihu_monopoly_ratio.stage.%s.source.%s.op.differenceAll",
			scene, stage, source.String())
		statsd.Gauge(differenceBucket, float64(monopolyNum)/float64(len(sourceDocIds)))
		statsd.Gauge(differenceAllBucket, float64(monopolyNum)/float64(len(filterItems)))
	}
}
