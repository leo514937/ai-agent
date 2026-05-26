package logic

import (
	"context"
	"encoding/json"
	"sync"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/condition"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

type GetQuestionDetailLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewGetQuestionDetailLogic(name string, config map[string]string) *GetQuestionDetailLogic {
	g := &GetQuestionDetailLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	g.UserFunc = g.userFunc
	g.AddCondition(condition.NewGetQuestionDetailControl("GetQuestionDetail"))
	return g
}

func (g *GetQuestionDetailLogic) generateRedisKey(ctx context.Context, questionID string, date string) string {
	return "ai_daily_question_" + questionID + "_" + date
}

func (g *GetQuestionDetailLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	logger := log.WithFields(ctx, map[string]interface{}{
		"source": request.Source,
	})
	keys := make([]string, 0)
	viewed := make(map[string]struct{})
	for _, v := range playListData.Latest7DaysViewedQuestionIDs {
		viewed[v] = struct{}{}
	}
	alreadyAdd := make(map[string]struct{})
	for _, questionID := range playListData.HighDimensionalQuestionIDs {
		if _, ok := viewed[questionID]; ok { // 已读过滤
			continue
		}
		if _, ok := alreadyAdd[questionID]; !ok {
			keys = append(keys, g.generateRedisKey(ctx, questionID, time.Now().Format("2006-01-02")))
			alreadyAdd[questionID] = struct{}{}
		}
	}
	for _, questionID := range playListData.QuestionIDs {
		if _, ok := viewed[questionID]; ok { // 已读过滤
			continue
		}
		if _, ok := alreadyAdd[questionID]; !ok {
			keys = append(keys, g.generateRedisKey(ctx, questionID, playListData.Date))
			alreadyAdd[questionID] = struct{}{}
		}
	}
	for _, questionID := range playListData.MostLikeQuestionIDs {
		if _, ok := viewed[questionID]; ok { // 已读过滤
			continue
		}
		if _, ok := alreadyAdd[questionID]; !ok {
			keys = append(keys, g.generateRedisKey(ctx, questionID, playListData.MostLikeDate))
			alreadyAdd[questionID] = struct{}{}
		}
	}
	logger.Infof(ctx, "GetQuestionDetail after remove duplicate.questionNum=%v", len(keys))
	if len(keys) == 0 {
		return nil
	}
	batchNum := 50
	wg := safe_group.NewGroup("GetQuestionDetail")
	questionMap := new(sync.Map)
	for i := 0; i < len(keys); i += batchNum {
		end := i + batchNum
		if end > len(keys) {
			end = len(keys)
		}
		redisKeys := keys[i:end]
		wg.Go(func() error {
			datas, err := resource.RedisByAIDaily.MGet(ctx, redisKeys...).Result()
			if err != nil || len(datas) == 0 {
				logger.Errorf(ctx, "[GetQuestionDetailLogic] MGET error: %v", err)
				return nil
			}
			for _, v := range datas {
				switch v.(type) {
				case string:
					var item *model.RedisQuestionDetail
					if err := json.Unmarshal([]byte(v.(string)), &item); err == nil {
						questionMap.Store(item.QuestionID, item)
					} else {
						logger.Errorf(ctx, "[GetQuestionDetailLogic] Unmarshal error: %v", err)
					}
				case []byte:
					var item *model.RedisQuestionDetail
					if err := json.Unmarshal(v.([]byte), &item); err == nil {
						questionMap.Store(item.QuestionID, item)
					} else {
						logger.Errorf(ctx, "[GetQuestionDetailLogic] Unmarshal error: %v", err)
					}
				}
			}
			return nil
		})
	}
	_ = wg.Wait()
	questionDetails := make([]*model.RedisQuestionDetail, 0)
	questionMap.Range(func(key, value any) bool {
		item := value.(*model.RedisQuestionDetail)
		questionDetails = append(questionDetails, item)
		return true
	})
	logger.Infof(ctx, "GetQuestionDetail End.questionNum=%v", len(questionDetails))
	playListData.QuestionDetails = questionDetails
	return nil
}
