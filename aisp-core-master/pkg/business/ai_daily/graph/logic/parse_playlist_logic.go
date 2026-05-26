package logic

import (
	"context"
	"encoding/json"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type ParsePlaylistLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewParsePlaylistLogic(name string, config map[string]string) *ParsePlaylistLogic {
	g := &ParsePlaylistLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	return g
}

func (g *ParsePlaylistLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	playListData := requestCtx.GetBizContext().GetPlayListData()
	playListData.HashToken = playListData.SnapShot.HashToken
	err := json.Unmarshal([]byte(playListData.SnapShot.JsonContent), &playListData.FinalQuestionDetails)
	if err != nil {
		return err
	}
	return nil
}
