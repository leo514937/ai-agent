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

type GetQuestionByThemeIDLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetQuestionByThemeIDLogic(name string, config map[string]string) *GetQuestionByThemeIDLogic {
	g := &GetQuestionByThemeIDLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	return g
}

func (g *GetQuestionByThemeIDLogic) generateRedisKey(ctx context.Context, themeID string, date string) string {
	return "ai_daily_" + themeID + "_" + date
}

func (g *GetQuestionByThemeIDLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	logger := log.WithFields(ctx, map[string]interface{}{
		"source": request.Source,
	})
	questionIDs := make([]string, 0)
	// 查询最近3天,某一天有数据则终止
	for i := 0; i < 3; i++ {
		date := time.Now().AddDate(0, 0, -i).Format("2006-01-02")
		keys := make([]string, 0)
		for _, theme := range playListData.ThemePairs {
			keys = append(keys, g.generateRedisKey(ctx, theme.ThemeID, date))
		}
		datas, err := resource.RedisByAIDaily.MGet(ctx, keys...).Result()
		if err != nil || len(datas) == 0 {
			continue
		}
		for _, v := range datas {
			if str, ok := v.(string); ok {
				questionIDs = append(questionIDs, strings.Split(str, ",")...)
			}
		}
		if len(questionIDs) > 0 {
			playListData.Date = date
			playListData.QuestionIDs = questionIDs
			logger.Infof(ctx, "GetQuestionByThemeID info.date=%v ids=%v", date, questionIDs)
			break
		}
	}
	return nil
}
