package logic

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/condition"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type GetPlaylistLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetPlaylistLogic(name string, config map[string]string) *GetPlaylistLogic {
	g := &GetPlaylistLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	g.SetChooseKeyFunc(g.chooseKey)
	g.AddCondition(condition.NewGetPlaylistControl("GetPlaylist"))
	return g
}

func (g *GetPlaylistLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	logger := log.WithFields(ctx, map[string]interface{}{
		"source": request.Source,
	})
	var data *model.TableDailySnapshot
	var err error
	if request.Token != "" { // 客态查询
		data, err = dao.DefaultDailySnapshotDAO.GetDailySnapshotByHashToken(ctx, request.Token)
		if err != nil {
			logger.Errorf(ctx, "GetDailySnapshotByHashToken failed.err=%v", err)
			return err
		}
		playListData.SnapShot = data
		playListData.UserID = data.UserID
		return nil
	}
	// 主态查询
	playListData.UserID = request.UserID
	data, err = dao.DefaultDailySnapshotDAO.GetDailySnapshotByUserIDAndDate(ctx, request.UserID, request.Date)
	if err != nil {
		logger.Errorf(ctx, "GetDailySnapshotByUserIDAndDate failed.err=%v", err)
		return err
	}
	playListData.SnapShot = data
	return nil
}

func (g *GetPlaylistLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	playListData := param.RequestContext.GetBizContext().GetPlayListData()
	request := param.RequestContext.GetBizContext().GetPlaylistRequest()
	if request.Token != "" && playListData.SnapShot == nil {
		// 客态直接返回
		return "Return"
	}
	if playListData.SnapShot != nil && playListData.SnapShot.JsonContent != "" && playListData.SnapShot.JsonContent != "null" {
		playListData.IsParseData = true
		return "Parse"
	}
	return "Generate"
}
