package response

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph/model"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
)

// BuildRecallResponseLogic 构造召回子图返回结构体
// @logicAuthor: wangran
type BuildRecallResponseLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewBuildRecallResponseLogic(name string, config map[string]string) *BuildRecallResponseLogic {
	res := &BuildRecallResponseLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.buildResponse
	res.NeedSignal = true
	return res
}

func (b *BuildRecallResponseLogic) buildResponse(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	// 避免空list，先做合并
	itemList := lo.Flatten(itemLists)
	respItemList := lo.Map(itemList, func(item *data_frame.ItemData[entities.Item], _ int) *entities.Item {
		return item.GetBizItem()
	})

	if recallContext, ok := requestCtx.GetBizContext().ProductContext().(*model.RecallContext); ok {
		request := recallContext.RequestInfo()
		if request.GetLimit() > 0 {
			respItemList = respItemList[0:util.Min(len(respItemList), int(request.GetLimit()))]
		}
	}

	requestCtx.GetBizContext().SetResponseItemList(respItemList)

	return itemList, nil
}
