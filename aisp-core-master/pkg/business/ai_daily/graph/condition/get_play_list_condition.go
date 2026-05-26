package condition

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	tools "git.in.zhihu.com/zrec/zrec-framework/pkg/core/plugins"
)

type GetPlaylistControl struct {
	*tools.DefaultConditionControl[entities.RequestContext, entities.User, entities.Item]
}

func NewGetPlaylistControl(name string) *GetPlaylistControl {
	condition := func(ctx context.Context, param *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
		playlistRequest := param.GetBizContext().GetPlaylistRequest()
		return playlistRequest.Token != "" || (playlistRequest.UserID != 0 && playlistRequest.Date != "")
	}

	return &GetPlaylistControl{
		DefaultConditionControl: tools.NewConditionControl(name, condition),
	}
}
