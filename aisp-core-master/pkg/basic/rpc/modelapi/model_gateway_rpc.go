package modelapi

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/zae"
	proto "git.in.zhihu.com/one-rpc-go/grpc-model_gateway/model_gateway"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/errors"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/halo"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/google/uuid"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type ModelGatewayRPC struct {
	client proto.ModelGatewayServiceClient
}

var (
	_ ModelTarget = (*ModelGatewayRPC)(nil)
)

func (r *ModelGatewayRPC) StreamChat(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse] {
	panic("not implemented")
}

func NewModelGatewayRPC() *ModelGatewayRPC {
	client, err := grpc.DialContext(context.Background(), "cup-admin-mg-grpc")
	if err != nil {
		log.Errorf(context.Background(), "dial cup-admin-mg-grpc err: %+v", err)

		panic(err)
	}

	return &ModelGatewayRPC{
		client: proto.NewModelGatewayServiceClient(client),
	}
}

func (r *ModelGatewayRPC) GenerateImage(ctx context.Context, req *dto.GenerateImageRequest) (*dto.GenerateImageResponse, error) {
	haloSpan := halo.NewHalo(ctx, "AISP_ModelGatewayRPC_GenerateImage", req.ModelName)
	nowTime := time.Now()
	defer func() { haloSpan.EndWithContext(ctx, time.Since(nowTime), nil) }()

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.rpc.ModelGatewayRPCImpl.GenerateImage",
		"req":  req,
	})
	if _, ok := proto.ImageModel_value[req.ModelName]; !ok {
		logger.Error(ctx, "model name is invalid")
		return nil, errors.ErrModelNotFound
	}
	logger.Info(ctx, "call model gateway")
	resp, err := r.client.SyncProcessTask(ctx, &proto.Request{
		App:          zae.App(),
		BizRequestId: lo.Must(uuid.NewRandom()).String(),
		TaskParam: &proto.TaskParam{
			TaskType: proto.TaskType_TYPE_IMAGE,
			TaskConfig: &proto.Param{
				ParamType: &proto.Param_ImageGenerationParam{
					ImageGenerationParam: &proto.ImageGenParam{
						Prompt: req.Prompt,
						N:      int32(req.Hyperparams.Count),
						Size:   proto.ImageGenParam_Size(proto.ImageGenParam_Size_value[req.Hyperparams.Size]),
						Model:  proto.ImageModel(proto.ImageModel_value[req.ModelName]),
						Params: &proto.ImageGenParam_Params{Item: lo.MapValues(req.Hyperparams.Extra, func(value any, _ string) string {
							return cast.ToString(value)
						})},
						Images: req.Images,
					},
				},
			},
		},
	})
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to call model gateway")
		return nil, err
	}

	logger = logger.WithField(ctx, "resp", resp)
	if resp.GetStatus() != proto.Status_suc {
		logger.Error(ctx, "model gateway returns error")
		return nil, fmt.Errorf("model gateway returns error: %s", resp.GetMessage())
	}

	images := resp.GetResponse().GetImageGenResponse().GetData()
	return &dto.GenerateImageResponse{Images: images}, nil
}

func (r ModelGatewayRPC) Chat(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error) {
	haloSpan := halo.NewHalo(ctx, "AISP_ModelGatewayRPC_Chat", req.ModelName)
	nowTime := time.Now()
	defer func() { haloSpan.EndWithContext(ctx, time.Since(nowTime), nil) }()

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.rpc.ModelGatewayRPCImpl.Chat",
		"req":  req,
	})
	logger.Info(ctx, "call model gateway")
	if _, ok := proto.ChatModel_value[req.ModelName]; !ok {
		logger.Error(ctx, "model name is invalid")
		return nil, errors.ErrModelNotFound
	}

	var maxTokens int32 = 0
	if strings.HasPrefix(req.ModelName, "CLAUDE_") {
		maxTokens = 4096
	}
	if req.ModelName == "GPT4VISION" || req.ModelName == "AZURE4V" {
		maxTokens = 4096
	}
	resp, err := r.client.SyncProcessTask(ctx, &proto.Request{
		App:          zae.App(),
		BizRequestId: lo.Must(uuid.NewRandom()).String(),
		TaskParam: &proto.TaskParam{
			TaskType: proto.TaskType_TYPE_CHAT,
			TaskConfig: &proto.Param{
				ParamType: &proto.Param_ChatParam{
					ChatParam: &proto.ChatParam{
						Messages: lo.Map(req.Messages, func(message *dto.ChatRequestMessage, _ int) *proto.ChatParam_Messages {
							return &proto.ChatParam_Messages{
								Content:         message.Content,
								Role:            message.Role.ToProto(),
								ChatContentInfo: dto.ChatContentInfoToProto(message.Content, message.Images),
							}
						}),
						Model:     proto.ChatModel(proto.ChatModel_value[req.ModelName]),
						MaxTokens: maxTokens,
					},
				},
			},
		},
	})
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to call model gateway")
		return nil, err
	}
	logger = logger.WithField(ctx, "resp", resp)
	if resp.GetStatus() != proto.Status_suc {
		logger.Error(ctx, "model gateway returns error")
		return nil, fmt.Errorf("model gateway returns error: %s", resp.GetMessage())
	}

	if resp.GetResponse().GetChatResponse().GetChoices()[0].GetFinishReason() == "content_filter" {
		logger.Error(ctx, "request blocked by content filter")
		err = fmt.Errorf("request blocked by content filter of model provider")
	}
	return &dto.ChatResponse{
		ModelName: req.ModelName,
		Content:   resp.GetResponse().GetChatResponse().GetChoices()[0].GetMessage().GetContent(),
		Usage: &dto.ChatResponseUsage{
			InputTokenCount:  int64(resp.GetResponse().GetChatResponse().GetUsage().GetPromptTokens()),
			OutputTokenCount: int64(resp.GetResponse().GetChatResponse().GetUsage().GetCompletionTokens()),
		},
	}, err
}

func (r ModelGatewayRPC) Responses(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error) {
	panic("not implemented")
}

func (r ModelGatewayRPC) StreamResponses(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse] {
	panic("not implemented")
}
