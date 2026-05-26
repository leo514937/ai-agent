package handler_zhihu

import (
	"time"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

type PlaygroundGenerateImageHandler struct {
	rest.BaseHandler

	modelDAO dao.ModelDAO

	modelGatewayRPC modelapi.ModelTarget
}

func NewPlaygroundGenerateImageHandler() rest.Handler {
	return &PlaygroundGenerateImageHandler{
		modelDAO:        dao.DefaultModelDAO,
		modelGatewayRPC: rpc.DefaultModelGatewayRouter,
	}
}

func (h *PlaygroundGenerateImageHandler) Post(ctx *rest.Context) (rest.Response, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "portal.dashboard.PlaygroundGenerateImageHandler.Get",
	})

	modelName := ctx.URLParam("modelName")
	if modelName == "" {
		return nil, rest.NewMalformRequestException("modelName is required", nil, nil)
	}

	model, err := h.modelDAO.GetModelByName(ctx, modelName)
	if err != nil {
		return nil, err
	}
	if model == nil {
		return nil, rest.NewResourceNotFoundException("model not found", nil, nil)
	}
	if model.Type != domainModel.ModelTypeImageGeneration {
		return nil, rest.NewResourceNotFoundException("model is not used for image generation", nil, nil)
	}

	var request *dto.GenerateImageRequest
	err = ctx.JSONArgs(&request)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to parse request")
		return nil, err
	}
	request.ModelName = modelName

	startAt := time.Now()
	resp, err := h.modelGatewayRPC.GenerateImage(ctx, request)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to generate image")
		return nil, err
	}
	elapsed := time.Since(startAt).Milliseconds()

	return ResponseSuccess(map[string]any{
		"elapsed_ms": elapsed,
		"images": lo.Map(resp.Images, func(image string, _ int) *ImageDTO {
			return &ImageDTO{
				URL: image,
			}
		}),
	})
}

type ImageDTO struct {
	URL string `json:"url"`
}

type PlaygroundChatHandler struct {
	rest.BaseHandler

	modelDAO dao.ModelDAO

	modelGatewayRPC modelapi.ModelTarget
}

func NewPlaygroundChatHandler() rest.Handler {
	return &PlaygroundChatHandler{
		modelDAO:        dao.DefaultModelDAO,
		modelGatewayRPC: rpc.DefaultModelGatewayRouter,
	}
}

type ChatRequest struct {
	Prompt  string                    `json:"prompt"`
	Images  []string                  `json:"images"`
	History []*dto.ChatRequestMessage `json:"history"`
}

func (h *PlaygroundChatHandler) Post(ctx *rest.Context) (rest.Response, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "portal.dashboard.PlaygroundChatHandler.Post",
	})

	modelName := ctx.URLParam("modelName")
	if modelName == "" {
		return nil, rest.NewMalformRequestException("modelName is required", nil, nil)
	}

	var request *ChatRequest
	err := ctx.JSONArgs(&request)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to parse request")
		return nil, err
	}

	model, err := h.modelDAO.GetModelByName(ctx, modelName)
	if err != nil {
		return nil, err
	}
	if model == nil {
		return nil, rest.NewResourceNotFoundException("model not found", nil, nil)
	}
	if model.Type != domainModel.ModelTypeChat {
		return nil, rest.NewResourceNotFoundException("model is not used for Chat", nil, nil)
	}

	messages := make([]*dto.ChatRequestMessage, 0)
	for _, message := range request.History {
		messages = append(messages, &dto.ChatRequestMessage{
			Content: message.Content,
			Role:    message.Role,
			Images:  message.Images,
		})
	}

	messages = append(messages, &dto.ChatRequestMessage{
		Content: request.Prompt,
		Role:    dto.ChatRequestMessageRoleUser,
		Images:  request.Images,
	})

	startAt := time.Now()
	resp, err := h.modelGatewayRPC.Chat(ctx, &dto.ChatRequest{
		ModelName: model.GetRPCName(),
		Messages:  messages,
	})
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to chat")
		return nil, err
	}
	elapsed := time.Since(startAt).Milliseconds()

	return ResponseSuccess(map[string]any{
		"elapsed_ms": elapsed,
		"message": &MessageDTO{
			Content: resp.GetContent(true),
		},
	})
}

type MessageDTO struct {
	Content string `json:"content"`
}
