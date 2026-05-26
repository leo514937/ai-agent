package word

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

var WordInnerFieldByIsExist = "isExistWord"

// WordExistPostLogic 判断词是否存在
type WordExistPostLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewWordExistPostLogic(name string, config map[string]string) *WordExistPostLogic {
	res := &WordExistPostLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.MergeFunc = res.checkIsExistWord
	res.NeedSignal = true
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (q *WordExistPostLogic) checkIsExistWord(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.WordExistPostLogic.checkIsExistWord")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	// 拍平 ItemLists
	items := lo.Flatten(itemLists)
	notWordItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().QueryType == proto.QueryType_QUERY_UNDEFINED
	})
	requestCtx.DataMap().SetBool(ctx, WordInnerFieldByIsExist, len(notWordItems) == 0)
	return items, nil
}

func (q *WordExistPostLogic) chooseKey(ctx context.Context, reqCtx *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	isExist, _ := reqCtx.RequestContext.DataMap().GetBool(ctx, WordInnerFieldByIsExist)
	if isExist {
		return entities.Break
	} else {
		return entities.Normal
	}
}
