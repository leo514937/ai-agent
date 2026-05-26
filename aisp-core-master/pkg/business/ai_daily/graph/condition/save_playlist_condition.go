package condition

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	tools "git.in.zhihu.com/zrec/zrec-framework/pkg/core/plugins"
)

type SavePlaylistControl struct {
	*tools.DefaultConditionControl[entities.RequestContext, entities.User, entities.Item]
}

func NewSavePlaylistControl(name string) *SavePlaylistControl {
	condition := func(ctx context.Context, param *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
		playlistData := param.GetBizContext().GetPlayListData()
		request := param.GetBizContext().GetPlaylistRequest()
		return len(playlistData.FinalQuestionDetails) > 0 && (request.Source == model.RequestSourceNormal || request.Source == model.RequestSourcePush)
	}

	return &SavePlaylistControl{
		DefaultConditionControl: tools.NewConditionControl(name, condition),
	}
}
