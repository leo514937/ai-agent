package logic

import (
	"context"
	"encoding/json"
	"time"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

type CalcQuestionSimLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewCalcQuestionSimLogic(name string, config map[string]string) *CalcQuestionSimLogic {
	c := &CalcQuestionSimLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	c.UserFunc = c.userFunc
	return c
}

func (c *CalcQuestionSimLogic) generateEmbeddingRedisKey(ctx context.Context, questionID string) string {
	return "ai_daily_ques_emb_" + questionID
}

func (c *CalcQuestionSimLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	playListData := requestCtx.GetBizContext().GetPlayListData()
	start := time.Now()
	defer func() {
		statsd.RecordTime("ai-daily-web.performance.calc_question_sim", time.Since(start).Milliseconds())
	}()
	// 获取question的redis key
	reCallQuestionIDs := make([]string, 0)
	redisKeys := make([]string, 0)
	for _, v := range playListData.QuestionDetails {
		reCallQuestionIDs = append(reCallQuestionIDs, v.QuestionID)
		redisKeys = append(redisKeys, c.generateEmbeddingRedisKey(ctx, v.QuestionID))
	}
	for _, v := range playListData.Latest3DaysViewedQuestionIDs {
		redisKeys = append(redisKeys, c.generateEmbeddingRedisKey(ctx, v))
	}
	if len(redisKeys) == 0 {
		return nil
	}
	// 从redis中获取question的embedding
	groupGetFunc := func(keys interface{}) interface{} {
		datas, err := resource.RedisByAIDaily.MGet(ctx, keys.([]string)...).Result()
		if err != nil || len(datas) == 0 {
			return nil
		}
		res := make(map[string]string)
		for index, val := range keys.([]string) {
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
	safe_group.BatchGet(50, redisKeys, groupGetFunc, &result)
	// 反序列化embedding
	embeddingMap := make(map[string][]float32)
	keys := make([]string, 0)
	for k, v := range result {
		embedding := make([]float32, 0)
		if err := json.Unmarshal([]byte(v), &embedding); err == nil {
			embeddingMap[k] = embedding
			keys = append(keys, k)
		}
	}
	// 计算问题间的相似度
	// 三天内下发的question与当天question相似度
	for _, q1 := range playListData.Latest3DaysViewedQuestionIDs {
		embedding1, ok := embeddingMap[c.generateEmbeddingRedisKey(ctx, q1)]
		if !ok {
			continue
		}
		for _, q2 := range reCallQuestionIDs {
			embedding2, ok2 := embeddingMap[c.generateEmbeddingRedisKey(ctx, q2)]
			if !ok2 {
				continue
			}
			val, err := util2.CosineByDefIgnoreNormalize(embedding1, embedding2, 0)
			if err == nil {
				playListData.ViewedQuestionSimMap[q1+"_"+q2] = val
				playListData.ViewedQuestionSimMap[q2+"_"+q1] = val
			}
		}
	}
	// 当天question之间的相似度
	for i := 0; i < len(reCallQuestionIDs); i++ {
		embedding1, ok := embeddingMap[c.generateEmbeddingRedisKey(ctx, reCallQuestionIDs[i])]
		if !ok {
			continue
		}
		for j := i + 1; j < len(reCallQuestionIDs); j++ {
			embedding2, ok2 := embeddingMap[c.generateEmbeddingRedisKey(ctx, reCallQuestionIDs[j])]
			if !ok2 {
				continue
			}
			val, err := util2.CosineByDefIgnoreNormalize(embedding1, embedding2, 0)
			if err == nil {
				playListData.Question2QuestionSimMap[reCallQuestionIDs[i]+"_"+reCallQuestionIDs[j]] = val
				playListData.Question2QuestionSimMap[reCallQuestionIDs[j]+"_"+reCallQuestionIDs[i]] = val
			}
		}
	}
	return nil
}
