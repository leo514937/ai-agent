package rerank_sort

import (
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

func SortGroup(otherKbSource conf.KbSource, kbSourceOrderArr []conf.KbSource, contents []*data_frame.ItemData[entities.Item]) map[conf.KbSource][]*data_frame.ItemData[entities.Item] {
	// 将 contents 分组
	groups := lo.GroupBy(contents, func(item *data_frame.ItemData[entities.Item]) conf.KbSource {
		// 针对站内内容特殊处理
		if !item.GetBizItem().GetItemMeta().IsOutLink() &&
			item.GetBizItem().GetItemMeta().DocId != 0 &&
			item.GetBizItem().GetItemMeta().DocType != content.DocType_Member &&
			item.GetBizItem().GetItemMeta().DocType != content.DocType_Text &&
			item.GetBizItem().GetItemMeta().DocType != content.DocType_Link &&
			item.GetBizItem().GetItemMeta().DocType != content.DocType_Unknown {
			if lo.Contains(kbSourceOrderArr, conf.KbSourceZhihu) {
				return conf.KbSourceZhihu
			}
		}
		for _, kbSource := range kbSourceOrderArr {
			if kbSource == otherKbSource {
				continue
			}
			if lo.Contains(item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources, kbSource) {
				return kbSource
			}
		}
		return otherKbSource
	})
	return groups
}
