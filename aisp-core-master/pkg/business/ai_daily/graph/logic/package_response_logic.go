package logic

import (
	"context"
	"strconv"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	core_model "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type PackageResponseLogic struct {
	*framework.UserLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewPackageResponseLogic(name string, config map[string]string) *PackageResponseLogic {
	p := &PackageResponseLogic{
		UserLogic: framework.NewUserLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	p.UserFunc = p.userFunc
	p.NeedSignal = true
	return p
}

func (p *PackageResponseLogic) userFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	request := requestCtx.GetBizContext().GetPlaylistRequest()
	playListData := requestCtx.GetBizContext().GetPlayListData()
	contents := make([]*model.QuestionItem, 0)
	finalDatas := playListData.FinalQuestionDetails
	if playListData.IsParseData {
		newQuestionDetail := make([]*model.RedisQuestionDetail, 0)
		for _, v := range playListData.FinalQuestionDetails {
			questionKey := conf.SecurityRegulateQuestionPrefix + v.QuestionID
			if _, ok := playListData.SecurityRegulateMap[questionKey]; ok {
				log.Infof(ctx, "[PackageResponseLogic] question security regulate.id=%v", v.QuestionID)
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
					log.Infof(ctx, "[PackageResponseLogic] answer security regulate.id=%v", answer.AnswerID)
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
				newQuestionDetail = append(newQuestionDetail, v)
			}
		}
		finalDatas = newQuestionDetail
	}
	for index, v := range finalDatas {
		answerItems := make([]*model.AnswerItem, 0)
		for _, val := range v.Answers {
			item := &model.AnswerItem{
				DocType:      "answer",
				AuthorName:   val.AnswerAuthorName,
				AuthorUrl:    val.AnswerAuthorUrl,
				AuthorHashID: val.AnswerAuthorHashID,
				Detail:       val.AnswerSummary,
				Url:          val.AnswerUrl,
				UrlToken:     val.AnswerUrlToken,
			}
			answerItems = append(answerItems, item)
		}
		questionItem := &model.QuestionItem{
			DocType:  "question",
			Title:    strconv.FormatInt(int64(index+1), 10) + "、" + v.QuestionTitle,
			Detail:   v.QuestionDetail,
			Url:      v.QuestionUrl,
			UrlToken: v.QuestionUrlToken,
			Items:    answerItems,
		}
		contents = append(contents, questionItem)
	}
	playListData.FinalQuestionDetails = finalDatas
	date := request.Date
	if request.Token != "" && playListData.SnapShot != nil {
		date = playListData.SnapShot.GenerateDate
	}
	title := "今日精选"
	if request.Token != "" && playListData.UserName != "" {
		title = "@" + playListData.UserName + "的今日精选"
	}
	response := &model.QueryPlaylistResponse{
		Title:      title,
		Date:       date,
		ShareToken: playListData.HashToken,
		Contents:   contents,
	}
	playListData.Response = response
	return nil
}
