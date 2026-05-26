package empty

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type EmptyBaseLogic struct {
	*logic.BaseLogic[entities.RequestContext]
}

func NewEmptyBaseLogic(name string, config map[string]string) *EmptyBaseLogic {
	res := &EmptyBaseLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}
	res.RealDoFunc = res.realDo
	return res
}

func (q *EmptyBaseLogic) realDo(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "empty.EmptyBaseLogic.realDo")
	defer span.Finish()
	span.LogFields(log.Message("start."))

	return nil
}
