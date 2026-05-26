package retrieval

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: MCP 召回后截断与标记模型使用

type ZhidaMCPRecallLimitLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewZhidaMCPRecallLimitLogic(name string, config map[string]string) *ZhidaMCPRecallLimitLogic {
	res := &ZhidaMCPRecallLimitLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.realMerge
	return res
}

func (z *ZhidaMCPRecallLimitLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "retrieval.KbDeepSearchAfterHandlerLogic.realMerge")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	items := lo.Flatten(itemLists)

	maxToken := cast.ToInt(requestCtx.GetBizContext().GetLogicConfig(z.GetName(), conf.RecallMergeMaxTokenField))
	totalToken := 0

	for _, item := range items {
		if item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk {
			currentItemToken := util.UnicodeLen(item.GetBizItem().Text)
			if maxToken != 0 && totalToken+currentItemToken > maxToken {
				break
			}
			totalToken += currentItemToken
			item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used = true
		}
	}

	return items, nil
}
