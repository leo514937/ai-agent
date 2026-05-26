package logic

import (
	"context"
	"encoding/json"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/condition"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type SavePlaylistLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewSavePlaylistLogic(name string, config map[string]string) *SavePlaylistLogic {
	s := &SavePlaylistLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	s.UserFunc = s.userFunc
	s.AddCondition(condition.NewSavePlaylistControl("SavePlaylist"))
	return s
}

func (s *SavePlaylistLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	contentBytes, err := json.Marshal(playListData.FinalQuestionDetails)
	if err != nil {
		return err
	}
	generateDate := request.Date
	if generateDate == "" {
		generateDate = time.Now().Format("2006-01-02")
	}
	dataMap := map[string]interface{}{
		"user_id":       request.UserID,
		"title":         "今日精选",
		"generate_date": generateDate,
		"json_content":  string(contentBytes),
		"hash_token":    playListData.HashToken,
		"req_source":    request.Source,
	}
	err = dao.DefaultDailySnapshotDAO.CreateDailySnapshot(ctx, dataMap)
	if err != nil {
		return err
	}
	return nil
}
