package logic

import (
	"context"
	"strings"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

type GetQuestionByHighLabelsLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetQuestionByHighLabelsLogic(name string, config map[string]string) *GetQuestionByHighLabelsLogic {
	g := &GetQuestionByHighLabelsLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	return g
}

func (g *GetQuestionByHighLabelsLogic) generateRedisKey(ctx context.Context, conceptItem string, date string) string {
	return "ai_daily_concept_" + conceptItem + "_" + date
}

func (g *GetQuestionByHighLabelsLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	logger := log.WithFields(ctx, map[string]interface{}{
		"source": request.Source,
	})
	date := time.Now().Format("2006-01-02")
	keys := make([]string, 0)
	for _, label := range playListData.HighDimensionalLabels {
		keys = append(keys, g.generateRedisKey(ctx, label, date))
	}
	if len(keys) == 0 {
		return nil
	}
	groupGetFunc := func(ids interface{}) interface{} {
		redisKeys := ids.([]string)
		datas, err := resource.RedisByAIDaily.MGet(ctx, redisKeys...).Result()
		if err != nil || len(datas) == 0 {
			return nil
		}
		res := make(map[string]string)
		for index, val := range redisKeys {
			if len(datas) <= index {
				continue
			}
			if str, ok := datas[index].(string); ok {
				res[val] = str

			}
		}
		return res
	}
	result := make(map[string]string)
	safe_group.BatchGet(50, keys, groupGetFunc, &result)
	questionIDs := make([]string, 0)
	for _, v := range result {
		if v == "" {
			continue
		}
		questionIDs = append(questionIDs, strings.Split(v, ",")...)
	}
	playListData.HighDimensionalQuestionIDs = util.UniqueElementSlice(questionIDs)
	logger.Infof(ctx, "GetQuestionByHighLabelsLogic info.ids=%v", playListData.HighDimensionalQuestionIDs)
	return nil
}
