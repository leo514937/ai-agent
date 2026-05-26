package condition

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	tools "git.in.zhihu.com/zrec/zrec-framework/pkg/core/plugins"
)

type GetUserInfoControl struct {
	*tools.DefaultConditionControl[entities.RequestContext, entities.User, entities.Item]
}

func NewGetUserInfoControl(name string) *GetUserInfoControl {
	condition := func(ctx context.Context, param *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
		request := param.GetBizContext().GetPlaylistRequest()
		return len(request.Token) > 0 // 客态才获取快照所属的用户名
	}
	return &GetUserInfoControl{
		DefaultConditionControl: tools.NewConditionControl(name, condition),
	}
}
