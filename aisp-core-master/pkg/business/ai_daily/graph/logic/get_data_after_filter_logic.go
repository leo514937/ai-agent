package logic

import (
	"context"
	"sort"
	"strconv"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	core_model "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type GetDataAfterFilterLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
	embRpc *impl.UnifiedEmbGrpcImpl
}

func NewGetDataAfterFilterLogic(name string, config map[string]string) *GetDataAfterFilterLogic {
	s := &GetDataAfterFilterLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	s.UserFunc = s.userFunc
	return s
}

func (c *GetDataAfterFilterLogic) getQuestionsAfterContentRegulate(ctx context.Context, playListData *model.PlayListData) []*model.RedisQuestionDetail {
	dataAfterContentRegulate := make([]*model.RedisQuestionDetail, 0)
	for _, v := range playListData.QuestionDetails {
		questionKey := conf.SecurityRegulateQuestionPrefix + v.QuestionID
		if _, ok := playListData.SecurityRegulateMap[questionKey]; ok {
			log.Infof(ctx, "[getQuestionsAfterContentRegulate] question security regulate.id=%v", v.QuestionID)
			continue
		}
		if questionID, err := strconv.ParseInt(v.QuestionID, 10, 64); err == nil {
			questionContent := core_model.Content{
				ContentID:   questionID,
				ContentType: content.DocType_Question,
			}
			if val, ok := playListData.ContentRegulateMap[questionContent]; ok && val != nil && val[rpc.VisitorCirculate] == rpc.InstructionValueDisable { // 问题管控
				continue
			}
		}
		answersItems := make([]*model.RedisAnswerDetail, 0)
		for _, answer := range v.Answers {
			answerKey := conf.SecurityRegulateAnswerPrefix + answer.AnswerID
			if _, ok := playListData.SecurityRegulateMap[answerKey]; ok {
				log.Infof(ctx, "[getQuestionsAfterContentRegulate] answer security regulate.id=%v", answer.AnswerID)
				continue
			}
			if answerID, err := strconv.ParseInt(answer.AnswerID, 10, 64); err == nil {
				answerContent := core_model.Content{
					ContentID:   answerID,
					ContentType: content.DocType_Answer,
				}
				if val, ok := playListData.ContentRegulateMap[answerContent]; ok && val != nil && val[rpc.VisitorCirculate] == rpc.InstructionValueDisable { // answer管控
					continue
				}
				answersItems = append(answersItems, answer)
			}
		}
		if len(answersItems) > 0 {
			v.Answers = answersItems
			dataAfterContentRegulate = append(dataAfterContentRegulate, v)
		}
	}
	return dataAfterContentRegulate
}

func (c *GetDataAfterFilterLogic) isQuestionSimilar(ctx context.Context, playListData *model.PlayListData, question *model.RedisQuestionDetail, questionArr []*model.RedisQuestionDetail) bool {
	exceedThreshold := false
	// 与候选池中的question相似度对比
	for _, item := range questionArr {
		key := question.QuestionID + "_" + item.QuestionID
		similarity, ok := playListData.Question2QuestionSimMap[key]
		if !ok {
			continue
		}
		if similarity > conf.QuestionSimilarThreshold {
			exceedThreshold = true
			break
		}
	}
	return exceedThreshold
}

func (c *GetDataAfterFilterLogic) getQuestionsAfterSimFilter(ctx context.Context, playListData *model.PlayListData, dataAfterContentRegulate []*model.RedisQuestionDetail) ([]*model.RedisQuestionDetail, []*model.RedisQuestionDetail) {
	newQuestionDetails := make([]*model.RedisQuestionDetail, 0)
	for _, newItem := range dataAfterContentRegulate {
		viewedExceedThreshold := false
		// 与过去下发的的question进行相似度对比
		for _, id := range playListData.Latest3DaysViewedQuestionIDs {
			key := newItem.QuestionID + "_" + id
			similarity, ok := playListData.ViewedQuestionSimMap[key]
			if ok && similarity > conf.QuestionSimilarThreshold {
				viewedExceedThreshold = true
				break
			}
		}
		if viewedExceedThreshold {
			continue
		}
		newQuestionDetails = append(newQuestionDetails, newItem)
	}
	// 分类，高维标签问题和普通内容
	isHighLabelQuestion := make(map[string]struct{})
	for _, v := range playListData.HighDimensionalQuestionIDs {
		isHighLabelQuestion[v] = struct{}{}
	}
	highLabelQuestionDetails := make([]*model.RedisQuestionDetail, 0)
	themeQuestionDetails := make([]*model.RedisQuestionDetail, 0)
	for _, v := range newQuestionDetails {
		if _, ok := isHighLabelQuestion[v.QuestionID]; ok {
			highLabelQuestionDetails = append(highLabelQuestionDetails, v)
		} else {
			themeQuestionDetails = append(themeQuestionDetails, v)
		}
	}
	sort.Slice(highLabelQuestionDetails, func(i, j int) bool {
		return highLabelQuestionDetails[i].QuestionLikes > highLabelQuestionDetails[j].QuestionLikes
	})
	sort.Slice(themeQuestionDetails, func(i, j int) bool {
		return themeQuestionDetails[i].QuestionLikes > themeQuestionDetails[j].QuestionLikes
	})
	// 高维标签问题相似度去重
	highLabelQuestionDetailsAfterFilter := make([]*model.RedisQuestionDetail, 0)
	for _, v := range highLabelQuestionDetails {
		if !c.isQuestionSimilar(ctx, playListData, v, highLabelQuestionDetailsAfterFilter) {
			highLabelQuestionDetailsAfterFilter = append(highLabelQuestionDetailsAfterFilter, v)
		}
	}
	// theme内容相似度去重
	themeQuestionDetailsAfterFilter := make([]*model.RedisQuestionDetail, 0)
	for _, v := range themeQuestionDetails {
		if !c.isQuestionSimilar(ctx, playListData, v, themeQuestionDetailsAfterFilter) {
			themeQuestionDetailsAfterFilter = append(themeQuestionDetailsAfterFilter, v)
		}
	}
	return highLabelQuestionDetailsAfterFilter, themeQuestionDetailsAfterFilter
}

func (c *GetDataAfterFilterLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	logger := log.WithFields(ctx, map[string]interface{}{
		"source": request.Source,
	})
	// 获取管控后的question
	dataAfterContentRegulate := c.getQuestionsAfterContentRegulate(ctx, playListData)
	logger.Infof(ctx, "GetDataAfterFilter ContentRegulate End.Num=%v", len(dataAfterContentRegulate))
	// question相似度去重
	playListData.HighLabelQuestionDetails, playListData.QuestionDetails = c.getQuestionsAfterSimFilter(ctx, playListData, dataAfterContentRegulate)
	logger.Infof(ctx, "AfterSimFilter End.highNum=%v themeNum=%v", len(playListData.HighLabelQuestionDetails), len(playListData.QuestionDetails))
	return nil
}
