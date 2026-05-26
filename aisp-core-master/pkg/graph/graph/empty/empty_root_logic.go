package empty

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 空root节点

// EmptyRootLogic 空RootLogic
type EmptyRootLogic struct {
	*framework.GetListLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewEmptyRootLogic(name string, config map[string]string) *EmptyRootLogic {
	res := &EmptyRootLogic{
		GetListLogic: framework.NeGetListLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.GetListFunc = res.emptyRoot
	res.BizNodeType = "request"
	return res
}

func (l *EmptyRootLogic) emptyRoot(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	return []*data_frame.ItemData[entities.Item]{}, nil
}
