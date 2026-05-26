package choose

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	word_service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/word"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 请求 token 或者 api_key 合法性校验

type RequestKeyVerifyLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	wordService word_service.WordMapperService
	redisDao    dao.UserRequestDao
	filterMap   map[string]func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool
}

func NewRequestKeyVerifyLogic(name string, config map[string]string) *RequestKeyVerifyLogic {
	res := &RequestKeyVerifyLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.realMerge
	// 选择条件边
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (r *RequestKeyVerifyLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "choose.ExpLogic.realMerge")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	return lo.Flatten(itemLists), nil
}

func (r *RequestKeyVerifyLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "RequestLegalityVerifyLogic.chooseKey")
	defer span.Finish()

	if false {
		return entities.Break
	}
	return entities.Normal
}
