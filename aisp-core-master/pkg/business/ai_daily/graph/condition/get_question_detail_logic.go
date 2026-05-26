package condition

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	tools "git.in.zhihu.com/zrec/zrec-framework/pkg/core/plugins"
)

type GetQuestionDetailControl struct {
	*tools.DefaultConditionControl[entities.RequestContext, entities.User, entities.Item]
}

func NewGetQuestionDetailControl(name string) *GetQuestionDetailControl {
	condition := func(ctx context.Context, param *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) bool {
		playlistData := param.GetBizContext().GetPlayListData()
		return len(playlistData.QuestionIDs) > 0 || len(playlistData.MostLikeQuestionIDs) > 0
	}

	return &GetQuestionDetailControl{
		DefaultConditionControl: tools.NewConditionControl(name, condition),
	}
}
