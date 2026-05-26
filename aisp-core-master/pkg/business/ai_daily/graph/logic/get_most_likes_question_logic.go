package logic

import (
	"context"
	"strings"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type GetMostLikeQuestionsLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetMostLikeQuestionsLogic(name string, config map[string]string) *GetMostLikeQuestionsLogic {
	g := &GetMostLikeQuestionsLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	return g
}

func (g *GetMostLikeQuestionsLogic) generateRedisKey(ctx context.Context, date string) string {
	return "ai_daily_hot_" + date
}

func (g *GetMostLikeQuestionsLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	logger := log.WithFields(ctx, map[string]interface{}{
		"source": request.Source,
	})
	// 查询最近3天,某一天有数据则终止
	for i := 0; i < 3; i++ {
		date := time.Now().AddDate(0, 0, -i).Format("2006-01-02")
		resp, err := resource.RedisByAIDaily.Get(ctx, g.generateRedisKey(ctx, date)).Result()
		if err != nil || len(resp) == 0 {
			continue
		}
		questionIDs := strings.Split(resp, ",")
		if len(questionIDs) > 0 {
			playListData.MostLikeDate = date
			playListData.MostLikeQuestionIDs = questionIDs
			logger.Infof(ctx, "GetMostLikeQuestions info.date=%v ids=%v", date, questionIDs)
			break
		}
	}
	return nil
}
