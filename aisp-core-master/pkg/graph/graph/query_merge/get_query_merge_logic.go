package query_merge

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type GetQueryMergeLogic struct {
	*framework.GetListLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetQueryMergeLogic(name string, config map[string]string) *GetQueryMergeLogic {
	res := &GetQueryMergeLogic{
		GetListLogic: framework.NeGetListLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.GetListFunc = res.queryMerge
	return res
}

func (o *GetQueryMergeLogic) queryMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	return []*data_frame.ItemData[entities.Item]{requestCtx.GetBizContext().GetQueryMerge().IntoFrameItem(requestCtx)}, nil
}
