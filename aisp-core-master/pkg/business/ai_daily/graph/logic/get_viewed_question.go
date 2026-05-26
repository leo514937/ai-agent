package logic

import (
	"context"
	"encoding/json"
	"strconv"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type GetViewedQuestionsLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetViewedQuestionsLogic(name string, config map[string]string) *GetViewedQuestionsLogic {
	g := &GetViewedQuestionsLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	return g
}

func (g *GetViewedQuestionsLogic) generateRedisKey(ctx context.Context, userID int64) string {
	return "viewed_question_" + strconv.FormatInt(userID, 10)
}

func (g *GetViewedQuestionsLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	logger := log.WithFields(ctx, map[string]interface{}{
		"source": request.Source,
	})
	requestDate, err := time.Parse("2006-01-02", request.Date)
	if err != nil {
		logger.Errorf(ctx, "parse request date error: %v", err)
	}
	timeBefore7Days := requestDate.AddDate(0, 0, -7).Format("2006-01-02")
	timeBefore1Days := requestDate.AddDate(0, 0, -1).Format("2006-01-02")
	timeBefore3Days := requestDate.AddDate(0, 0, -3).Format("2006-01-02")
	contents, err := dao.DefaultDailySnapshotDAO.GetDailySnapshotsByUserIDBetweenDate(ctx, request.UserID, timeBefore7Days, timeBefore1Days)
	if err != nil || len(contents) == 0 {
		return err
	}
	for _, content := range contents {
		details := make([]*model.RedisQuestionDetail, 0)
		err := json.Unmarshal([]byte(content.JsonContent), &details)
		if err != nil {
			continue
		}
		for _, v := range details {
			playListData.Latest7DaysViewedQuestionIDs = append(playListData.Latest7DaysViewedQuestionIDs, v.QuestionID)
		}
		if content.GenerateDate >= timeBefore3Days {
			for _, v := range details {
				playListData.Latest3DaysViewedQuestionIDs = append(playListData.Latest3DaysViewedQuestionIDs, v.QuestionID)
			}
		}
	}
	logger.Infof(ctx, "GetViewedQuestions End.ids=%v", playListData.Latest7DaysViewedQuestionIDs)
	return nil
}
