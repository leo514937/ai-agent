package handler_zhihu

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware"
	"github.com/samber/lo"
)

type FeedbacksHandler struct {
	rest.BaseHandler

	httpClient *http.Client
}

func NewFeedbacksHandler() *FeedbacksHandler {
	return &FeedbacksHandler{
		httpClient: &http.Client{},
	}
}

func (h *FeedbacksHandler) Post(ctx *rest.Context) (rest.Response, error) {
	var feedbackDTO FeedbackDTO
	err := ctx.JSONArgs(&feedbackDTO)
	if err != nil {
		return nil, err
	}

	logger := log.WithFields(ctx, log.Fields{
		"func":        "FeedbacksHandler.Post",
		"feedbackDTO": feedbackDTO,
	})

	user := middleware.AuthingUserFromContext(ctx)

	qywxMessageDTO := &QYWXMessageDTO{
		MsgType: "markdown",
		Markdown: struct {
			Content string `json:"content"`
		}{
			Content: fmt.Sprintf("#### AISP 的新增反馈\n%s\n##### 环境\n1. 所在页面: `%s`\n2. UA: `%s`\n#### 反馈内容\n%s\n", user.Email, ctx.Request.Referer(), ctx.Request.UserAgent(), feedbackDTO.Content),
		},
	}
	resp, err := h.httpClient.Post(
		config.GetString("qywx.bot_url", ""),
		"application/json",
		bytes.NewReader(lo.Must(json.Marshal(qywxMessageDTO))),
	)
	if err != nil {
		logger.WithError(err).Error("send qywx message error")
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		logger.WithField("statusCode", resp.StatusCode).Error("send qywx message error")
		return nil, fmt.Errorf("send qywx message error, statusCode=[%d]", resp.StatusCode)
	}

	logger.Info("send qywx message success")
	return ResponseSuccess(nil)
}

type FeedbackDTO struct {
	Content string `json:"content"`
}

type QYWXMessageDTO struct {
	MsgType  string `json:"msgtype"`
	Markdown struct {
		Content string `json:"content"`
	} `json:"markdown"`
}
