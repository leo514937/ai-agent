package response

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// DefItemRespLogic Item 默认返回
type DefItemRespLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewDefItemRespLogic(name string, config map[string]string) *DefItemRespLogic {
	res := &DefItemRespLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.MergeFunc = res.respItem
	return res
}

func (c *DefItemRespLogic) respItem(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "response.DefItemRespLogic.respItem")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "DefItemRespLogic",
	})

	if len(itemLists) == 0 {
		logger.Warn(ctx, "items res is null")
		requestCtx.GetBizContext().SetResponseItemList([]*entities.Item{})
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 多路召回 扁平化处理
	flattenItems := lo.Flatten(itemLists)

	var itemRespList []*entities.Item
	for _, v := range flattenItems {
		itemRespList = append(itemRespList, v.GetBizItem())
	}
	requestCtx.GetBizContext().SetResponseItemList(itemRespList)
	return flattenItems, nil
}
