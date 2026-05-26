package ai_daily_rpc

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/ai_daily"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type AiDailyRecommendServiceImpl struct {
}

func NewAiDailyRecommendServiceImpl() *AiDailyRecommendServiceImpl {
	return &AiDailyRecommendServiceImpl{}
}

func (o *AiDailyRecommendServiceImpl) AiDailyRecommend(ctx context.Context, req *ai_daily.AiDailyRecommendRequest) (*ai_daily.AiDailyRecommendResponse, error) {
	// 从 thrift 请求中提取参数
	userID := req.GetUserID()
	date := req.GetDate()
	token := req.GetToken()
	source := req.GetSource()

	// 如果 source 为空，设置默认值
	if source == "" {
		source = model.RequestSourceNormal
	}

	logger := log.WithFields(ctx, map[string]interface{}{
		"user_id": userID,
		"date":    date,
		"token":   token,
		"source":  source,
	})

	// 构建请求
	bizRequest := &model.QueryPlaylistRequest{
		UserID: userID,
		Date:   date,
		Token:  token,
		Source: source,
	}

	// 获取当前图配置
	bizRequestContext := entities.NewRequestContextFromAIDailyRequest(bizRequest)
	_, _, _, err := graph.RunGraph(ctx, bizRequestContext, nil)

	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "run QueryPlaylist graph failed => BuildQuery")
		return &ai_daily.AiDailyRecommendResponse{
			Code:    1,
			Message: "服务器内部错误",
		}, nil
	}

	playlistData := bizRequestContext.GetPlayListData().Response
	if playlistData == nil {
		return &ai_daily.AiDailyRecommendResponse{
			Code:    1,
			Message: "未找到数据",
		}, nil
	}

	// 转换数据格式
	thriftResponse := &ai_daily.QueryPlaylistResponse{
		Title:      playlistData.Title,
		Date:       playlistData.Date,
		ShareToken: playlistData.ShareToken,
	}

	// 转换所有内容项数组
	if len(playlistData.Contents) > 0 {
		var questionItems []*ai_daily.QuestionItem

		for _, content := range playlistData.Contents {
			questionItem := &ai_daily.QuestionItem{
				DocType:  content.DocType,
				Title:    content.Title,
				Detail:   &content.Detail,
				URL:      &content.Url,
				URLToken: &content.UrlToken,
			}
			if len(content.Items) > 0 {
				var answerItems []*ai_daily.AnswerItem

				for _, answer := range content.Items {
					answerItem := &ai_daily.AnswerItem{
						DocType:      answer.DocType,
						AuthorName:   answer.AuthorName,
						AuthorURL:    &answer.AuthorUrl,
						AuthorHashID: &answer.AuthorHashID,
						Detail:       &answer.Detail,
						URL:          &answer.Url,
						URLToken:     &answer.UrlToken,
					}
					answerItems = append(answerItems, answerItem)
				}
				questionItem.Items = answerItems
			}
			questionItems = append(questionItems, questionItem)
		}
		thriftResponse.Contents = questionItems
	}

	return &ai_daily.AiDailyRecommendResponse{
		Code:         0,
		Message:      "SUCCESS",
		PlaylistData: thriftResponse,
	}, nil
}
