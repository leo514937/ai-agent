package logic

import (
	"context"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type SelectDataLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
	embRpc *impl.UnifiedEmbGrpcImpl
}

func NewSelectDataLogic(name string, config map[string]string) *SelectDataLogic {
	s := &SelectDataLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	s.UserFunc = s.userFunc
	return s
}

func (c *SelectDataLogic) canAddResult(ctx context.Context, bayesCountMap, entityCountMap map[string]int, entityWords []string, question *model.RedisQuestionDetail) bool {
	if bayesCountMap[question.BayesItem] >= conf.BayesLimit {
		return false
	}
	exceedEntityLimit := false
	for _, word := range entityWords {
		if entityCountMap[word] >= conf.EntityLimit {
			exceedEntityLimit = true
			break
		}
	}
	if exceedEntityLimit {
		return false
	}
	return true
}

func (c *SelectDataLogic) isThemeSimilar(ctx context.Context, playListData *model.PlayListData, question *model.RedisQuestionDetail, questionArr []*model.RedisQuestionDetail) bool {
	exceedThreshold := false
	// 与候选池中的theme相似度对比
	for _, item := range questionArr {
		key := question.LabelContent + "_" + item.LabelContent
		similarity, ok := playListData.Theme2ThemeSimMap[key]
		if !ok {
			continue
		}
		if similarity > conf.ThemeSimilarThreshold {
			exceedThreshold = true
			break
		}
	}
	return exceedThreshold
}

func (c *SelectDataLogic) getHighDimensionalLabelData(ctx context.Context, playListData *model.PlayListData) []*model.RedisQuestionDetail {
	// 按高维标签词分类
	highDimensionalLabel2Data := make(map[string][]*model.RedisQuestionDetail)
	for _, v := range playListData.HighLabelQuestionDetails {
		for _, item := range strings.Split(v.ConceptItem, ",") {
			highDimensionalLabel2Data[item] = append(highDimensionalLabel2Data[item], v)
		}
	}
	// 高维标签词内部按questionLikes倒序排列
	for _, v := range highDimensionalLabel2Data {
		sort.Slice(v, func(i, j int) bool {
			return v[i].QuestionLikes > v[j].QuestionLikes
		})
	}
	// 筛选有内容的高维标签词
	finalLabels := make([]string, 0)
	for _, v := range playListData.HighDimensionalLabels {
		if _, ok := highDimensionalLabel2Data[v]; ok {
			finalLabels = append(finalLabels, v)
		}
	}
	// 按高维标签顺序取问题, 打散。标签1-问题1，标签2-问题1，标签3-问题1，标签1-问题2，标签2-问题2，标签3-问题2
	finalQuestions := make([]*model.RedisQuestionDetail, 0)
	finalQuestionIndex := make([]int, len(finalLabels))
	alreadyAdd := make(map[string]struct{})
	for i := 0; i < conf.HighLabelLimit; i++ {
		for index, label := range finalLabels {
			for j := finalQuestionIndex[index]; j < len(highDimensionalLabel2Data[label]); j++ {
				question := highDimensionalLabel2Data[label][j]
				if _, ok := alreadyAdd[question.QuestionID]; !ok {
					alreadyAdd[question.QuestionID] = struct{}{}
					question.Source = conf.DataSourceHighLabel
					finalQuestions = append(finalQuestions, question)
					if len(finalQuestions) >= conf.DataTotalQuestion {
						return finalQuestions
					}
					finalQuestionIndex[index] = j + 1
					break
				}
			}
		}
	}
	return finalQuestions
}

func (c *SelectDataLogic) getThemeDataAndOtherData(ctx context.Context, playListData *model.PlayListData) (map[string][]*model.RedisQuestionDetail, []string, []*model.RedisQuestionDetail) {
	originTheme := make(map[string]struct{}) // 用户感兴趣的theme
	for _, v := range playListData.ThemePairs {
		originTheme[v.ThemeName] = struct{}{} //
	}
	themeName2Data := make(map[string][]*model.RedisQuestionDetail)
	otherThemeDatas := make([]*model.RedisQuestionDetail, 0) // 兜底的兴趣数据
	for _, v := range playListData.QuestionDetails {
		themeName := v.LabelContent
		if _, ok := originTheme[themeName]; !ok {
			otherThemeDatas = append(otherThemeDatas, v)
			continue
		}
		themeName2Data[themeName] = append(themeName2Data[themeName], v)
	}
	// 兜底的兴趣问题按热度分倒序排列
	sort.Slice(otherThemeDatas, func(i, j int) bool {
		return otherThemeDatas[i].QuestionLikes > otherThemeDatas[j].QuestionLikes
	})
	// 原始兴趣的theme下的问题按热度分倒序排列
	for _, v := range themeName2Data {
		sort.Slice(v, func(i, j int) bool {
			return v[i].QuestionLikes > v[j].QuestionLikes
		})
	}
	// 删除原始兴趣中没有召回数据的兴趣
	originThemeHaveData := make([]string, 0)
	for _, v := range playListData.ThemePairs {
		if _, ok := themeName2Data[v.ThemeName]; ok {
			originThemeHaveData = append(originThemeHaveData, v.ThemeName)
		}
	}
	return themeName2Data, originThemeHaveData, otherThemeDatas
}

func (c *SelectDataLogic) getFinalThemeAndQuestionNum(ctx context.Context, playListData *model.PlayListData, originThemeHaveData []string) ([]string, int) {
	// 原始兴趣按相似度去重
	finalThemes := make([]string, 0)
	if len(originThemeHaveData) <= conf.ThemeCountLimit10 { // 低频用户不打散theme
		finalThemes = originThemeHaveData
	} else {
		for _, v := range originThemeHaveData {
			exceedThreshold := false
			// 与候选池中的theme相似度对比
			for _, item := range finalThemes {
				key := v + "_" + item
				similarity, ok := playListData.Theme2ThemeSimMap[key]
				if !ok {
					continue
				}
				if similarity > conf.ThemeSimilarThreshold {
					exceedThreshold = true
					break
				}
			}
			// 如果相似度不大于阈值，加入候选池
			if !exceedThreshold {
				finalThemes = append(finalThemes, v)
			}
		}
	}
	// 原始兴趣下每个取x个问题
	questionNum := conf.QuestionNum1PerTheme
	if len(finalThemes) <= conf.ThemeCountLimit5 {
		questionNum = conf.QuestionNum3PerTheme
	} else if len(finalThemes) <= conf.ThemeCountLimit10 {
		questionNum = conf.QuestionNum2PerTheme
	}
	// 如果只取1个question，会取top1，避免top1问题被问题相似度过滤，不使用去重后的theme
	// 在后续添加问题进候选池时，做theme间的相似度过滤
	if questionNum == 1 {
		finalThemes = originThemeHaveData
	}
	return finalThemes, questionNum
}

func (c *SelectDataLogic) statsd(ctx context.Context, playListData *model.PlayListData) {
	statsd.Increment(fmt.Sprintf("ai-daily-web.result.num.%d.count", len(playListData.FinalQuestionDetails)))
	countMap := make(map[string]int)
	for _, v := range playListData.FinalQuestionDetails {
		countMap[v.Source]++
	}
	for k, v := range countMap {
		source := k
		if source == "" {
			source = "unknown"
		}
		statsd.TimeInMilliseconds(fmt.Sprintf("ai-daily-web.result.source.%s.cnt", k), float64(v))
	}
}

func (c *SelectDataLogic) generateHashToken(userID int64) string {
	generateDate := time.Now().Format("2006-01-02")
	randStr, _ := util.SecureRandString(30)
	hashToken := util.MD5(strconv.FormatInt(userID, 10) + "_" + generateDate + "_" + randStr)
	return hashToken
}

func (c *SelectDataLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	logger := log.WithFields(ctx, map[string]interface{}{
		"source": request.Source,
	})
	defer func() {
		if r := recover(); r != nil {
			logger.Errorf(ctx, "[SelectDataLogic] panic: %v", r)
		}
	}()
	defer func() {
		playListData.CardGenerateTime = time.Now()
		playListData.HashToken = c.generateHashToken(request.UserID)
		c.statsd(ctx, playListData)
	}()
	// 获取高维标签内容
	finalQuestionDetails := c.getHighDimensionalLabelData(ctx, playListData)
	logger.Infof(ctx, "SelectData.highLabelDataNum=%v", len(finalQuestionDetails))
	if len(finalQuestionDetails) >= conf.DataTotalQuestion {
		playListData.FinalQuestionDetails = finalQuestionDetails[:conf.DataTotalQuestion]
		return nil
	}
	// 获取原始兴趣数据以及兜底的兴趣数据
	themeName2Data, originThemeHaveData, otherThemeDatas := c.getThemeDataAndOtherData(ctx, playListData)
	logger.Infof(ctx, "SelectData beign.originThemeHaveData=%v otherDataNum=%v", originThemeHaveData, len(otherThemeDatas))
	// 获取最后的兴趣列表，以及每个theme下取的问题数量
	finalThemes, questionNum := c.getFinalThemeAndQuestionNum(ctx, playListData, originThemeHaveData)
	logger.Infof(ctx, "SelectData after theme similar filter.finalThemes=%v", finalThemes)
	// 选取最后的question，先从兴趣列表中选数据，再从兜底问题中取数据
	bayesCountMap := make(map[string]int)
	entityCountMap := make(map[string]int)
	for _, v := range finalQuestionDetails {
		bayesCountMap[v.BayesItem]++
		for _, word := range strings.Split(v.KeyEntity, ",") {
			entityCountMap[word]++
		}
	}
	finalThemeQuestionIndex := make([]int, len(finalThemes))
	for i := 0; i < questionNum; i++ {
		for index, v := range finalThemes {
			maxIndex := 1 // 非低频用户只取第一个question
			if questionNum > 1 {
				maxIndex = len(themeName2Data[v])
			}
			for j := finalThemeQuestionIndex[index]; j < maxIndex; j++ {
				question := themeName2Data[v][j]
				// 只取top1时需要判断theme相似度
				if questionNum == 1 && c.isThemeSimilar(ctx, playListData, question, finalQuestionDetails) {
					continue
				}
				entityWords := strings.Split(question.KeyEntity, ",")
				if c.canAddResult(ctx, bayesCountMap, entityCountMap, entityWords, question) {
					question.Source = conf.DataSourceTheme
					finalQuestionDetails = append(finalQuestionDetails, question)
					if len(finalQuestionDetails) >= conf.DataTotalQuestion {
						playListData.FinalQuestionDetails = finalQuestionDetails
						return nil
					}
					bayesCountMap[question.BayesItem]++
					for _, word := range entityWords {
						entityCountMap[word]++
					}
					finalThemeQuestionIndex[index] = j + 1
					break
				}
			}
		}
	}
	// 不足10个从兜底问题中选择，根据兴趣相似度判断是否去重
	for _, v := range otherThemeDatas {
		// 如果相似度大于阈值，过滤
		if c.isThemeSimilar(ctx, playListData, v, finalQuestionDetails) {
			continue
		}
		entityWords := strings.Split(v.KeyEntity, ",")
		if c.canAddResult(ctx, bayesCountMap, entityCountMap, entityWords, v) {
			v.Source = conf.DataSourceOther
			finalQuestionDetails = append(finalQuestionDetails, v)
			if len(finalQuestionDetails) >= conf.DataTotalQuestion {
				playListData.FinalQuestionDetails = finalQuestionDetails
				return nil
			}
			bayesCountMap[v.BayesItem]++
			for _, word := range entityWords {
				entityCountMap[word]++
			}
		}
	}
	playListData.FinalQuestionDetails = finalQuestionDetails
	return nil
}
