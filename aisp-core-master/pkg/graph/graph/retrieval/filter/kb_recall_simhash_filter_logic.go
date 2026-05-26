package filter

import (
	"context"
	"fmt"

	"git.in.zhihu.com/pb-go/zai-proto/ai/common"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/spf13/cast"
)

const simHashFilterReasonFmt = "simhash_filter_%s_%d"

// KbRecallSimHashFilterLogic
// @logicAuthor: liupenghe
// @logicInfo: 召回后基于 simhash 过滤重复内容
type KbRecallSimHashFilterLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
	embRpc       *impl.UnifiedEmbGrpcImpl
	defThreshold float64
}

func NewKbRecallSimHashFilterLogic(name string, config map[string]string) *KbRecallSimHashFilterLogic {
	res := &KbRecallSimHashFilterLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.NeedFilterItemsFunc = res.needFilterItems
	res.embRpc = impl.NewUnifiedEmbImplForSearch() // 初始化 embRpc
	res.defThreshold = 0.96
	return res
}

func (l *KbRecallSimHashFilterLogic) needFilterItems(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[*data_frame.ItemData[entities.Item]]string, error) {
	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallSimHashFilterLogic.realFilter",
	})
	// 实现基于 simhash 的过滤逻辑
	threshold := cast.ToFloat64(requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.RecallFilterSimHashThreshold.ToConvert()))
	if threshold < 0 || threshold > 1 {
		threshold = l.defThreshold
	}

	// 上下文长度限制
	contentLimit := cast.ToInt(requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.RecallFilterSimHashContentLimit.ToConvert()))

	wg := safe_group.NewGroupWithTimeout("SimHashFilter-Embedding", 3000).SetLimit(100)
	syncMap := util2.NewSyncMap[int, []float32]()
	for i, item := range items {
		i := i
		item := item
		wg.Go(func() error {
			// 获取 embedding，生成 simhash 的二进制值
			if item.GetBizItem().GetItemMeta().Content == "" {
				return nil
			}

			itemTitle := item.GetBizItem().GetItemMeta().Title
			itemContent := item.GetBizItem().GetItemMeta().Content

			// content 最大长度限制
			content := itemTitle + itemContent
			if contentLimit > 0 {
				content = itemTitle + util2.UnicodeSubstr(itemContent, 0, zrecUtil.Min(contentLimit, util2.UnicodeLen(itemContent)))
			}
			emb := l.embRpc.GetEmbedding(ctx, content, common.EmbeddingType_SimHashEmbedding)
			syncMap.Set(i, emb)
			return nil
		})
	}
	wgErr := wg.Wait()
	if wgErr != nil {
		logger.Errorf(ctx, "get embedding err: %+v", wgErr)
	}

	n := len(items)
	uf := util.NewUnionFind()
	// 计算 item 之间的相似度
	// 对于超过阈值的，则认为两篇 doc 属于同一篇
	for i := 0; i < n-1; i++ {
		for j := i + 1; j < n; j++ {
			iItemSimHash, existI := syncMap.Get(i)
			jItemSimHash, existJ := syncMap.Get(j)
			if !existI || !existJ {
				continue
			}
			similarity, err := util2.CosineByDefIgnoreNormalize01(iItemSimHash, jItemSimHash, 0)
			if err != nil {
				continue
			}
			// 如果相似度大于阈值，则将两个 item 合并到同一个集合中
			if similarity >= threshold {
				uf.Union(i, j)
			}
		}
	}

	// 基于并查集算法每个重复集合里只保留1篇
	// 找出每个集合的代表
	representatives := make(map[int]struct{})
	for i := 0; i < n; i++ {
		root := uf.Find(i)
		if _, exists := representatives[root]; !exists {
			representatives[root] = struct{}{}
		}
	}

	// 构建结果文档集合
	resMap := make(map[*data_frame.ItemData[entities.Item]]string)
	for i := 0; i < n; i++ {
		if _, exists := representatives[i]; !exists {
			resMap[items[i]] = fmt.Sprintf(simHashFilterReasonFmt, items[i].GetBizItem().ItemMeta.DocType.String(), items[i].GetBizItem().ItemMeta.DocId)
		}
	}

	return resMap, nil
}
