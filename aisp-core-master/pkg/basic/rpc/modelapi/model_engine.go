package modelapi

import (
	"context"
	"errors"
	"fmt"
	"io"
	"time"

	"git.in.zhihu.com/go/utils"
	proto "git.in.zhihu.com/one-rpc-go/grpc-model_engine/model_engine_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/halo"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

const RequestTimeout = 10 * time.Minute

type ChatResult struct {
	Content string
	Usage   *Usage
	Model   string
}

type Usage struct {
	InputTokenCount  int64
	OutputTokenCount int64
}

var (
	_ ModelTarget = (*ModelEngineRPC)(nil)
)

func toDomainRole(role dto.ChatRequestMessageRole) domainModel.MessageRole {
	switch role {
	case dto.ChatRequestMessageRoleUser:
		return domainModel.MessageRoleUser
	case dto.ChatRequestMessageRoleAI:
		return domainModel.MessageRoleAI
	default:
		panic(fmt.Sprintf("unknown role: %s", role))
	}
}

func (r *ModelEngineRPC) innerChat(ctx context.Context, modelContext *model.Context, taskName string) (content string, usage *Usage, modelName string, err error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"modelContext": modelContext,
		"taskName":     taskName,
	})

	ctx, cancel := context.WithTimeout(ctx, RequestTimeout)
	defer cancel()
	resp, err := r.client.Chat(ctx, &proto.ChatRequest{
		Context: &proto.Context{
			AiProfile:   modelContext.AIProfile,
			UserProfile: modelContext.UserProfile,
			Prompt:      modelContext.Prompt,
			RecentMessages: lo.Map(modelContext.RecentMessages, func(message *model.Message, _ int) *proto.Context_Message {
				return &proto.Context_Message{
					Content: message.Content,
					Role:    proto.Context_Message_Role(proto.Context_Message_Role_value[string(message.Role)]),
				}
			}),
		},
		Task: &proto.Task{
			Name: taskName,
		},
	})

	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "model-engine-service chat failed")
		return "", nil, "", err
	}

	if resp.Usage.InputTokenCount < 0 {
		logger.Error(ctx, "model-engine-service chat error, input token count is negative")
		resp.Usage.InputTokenCount = 0
	}
	if resp.Usage.OutputTokenCount < 0 {
		logger.Error(ctx, "model-engine-service chat error, output token count is negative")
		resp.Usage.OutputTokenCount = 0
	}
	return resp.Content, &Usage{
		InputTokenCount:  resp.Usage.InputTokenCount,
		OutputTokenCount: resp.Usage.OutputTokenCount,
	}, resp.GetModel().GetName(), nil
}

func (r *ModelEngineRPC) innerStreamChat(ctx context.Context, modelContext *model.Context, taskName string) <-chan util.Progress[*ChatResult] {
	logger := log.WithFields(ctx, map[string]interface{}{
		"modelContext": modelContext,
		"taskName":     taskName,
	})

	ret := make(chan util.Progress[*ChatResult])

	utils.SafelyGo(func() {
		defer close(ret)

		ctx, cancel := context.WithTimeout(ctx, RequestTimeout)
		defer cancel()

		stream, err := r.client.ChatStream(ctx, &proto.ChatRequest{
			Context: &proto.Context{
				AiProfile:   modelContext.AIProfile,
				UserProfile: modelContext.UserProfile,
				Prompt:      modelContext.Prompt,
				RecentMessages: lo.Map(modelContext.RecentMessages, func(message *model.Message, _ int) *proto.Context_Message {
					return &proto.Context_Message{
						Content: message.Content,
						Role:    proto.Context_Message_Role(proto.Context_Message_Role_value[string(message.Role)]),
					}
				}),
			},
			Task: &proto.Task{
				Name: taskName,
			},
		})

		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "model-engine-service chat failed")
			ret <- util.Progress[*ChatResult]{E: err}
			return
		}

		for {
			resp, err := stream.Recv()
			if errors.Is(err, io.EOF) {
				logger.Info(ctx, "model-engine-service ChatStream end")
				return
			}
			if err != nil {
				logger.WithError(ctx, err).Error(ctx, "model-engine-service chat failed")
				ret <- util.Progress[*ChatResult]{E: err}
				return
			}
			ret <- util.Progress[*ChatResult]{V: &ChatResult{
				Content: resp.Content,
				Usage: &Usage{
					InputTokenCount:  resp.Usage.InputTokenCount,
					OutputTokenCount: resp.Usage.OutputTokenCount,
				},
				Model: resp.Model.GetName(),
			}}
		}
	}, func(err error) {})

	return ret
}

type ModelEngineRPC struct {
	client proto.ModelEngineServiceClient
}

func NewModelEngineRPC() *ModelEngineRPC {
	target := "model-engine-grpc"
	ctx := context.Background()

	logger := log.WithField(ctx, "target", target)

	conn, err := grpc.DialContext(context.Background(), target)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "dial model-engine-grpc failed")

		panic(err)
	}

	return &ModelEngineRPC{
		client: proto.NewModelEngineServiceClient(conn),
	}
}

func (a ModelEngineRPC) GenerateImage(ctx context.Context, req *dto.GenerateImageRequest) (*dto.GenerateImageResponse, error) {
	panic("not implemented")
}

func (a ModelEngineRPC) Responses(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error) {
	panic("not implemented")
}

func (a ModelEngineRPC) StreamResponses(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse] {
	panic("not implemented")
}

func (a ModelEngineRPC) Chat(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error) {
	haloSpan := halo.NewHalo(ctx, "AISP_ModelEngineRPC_Chat", req.ModelName)
	nowTime := time.Now()
	defer func() { haloSpan.EndWithContext(ctx, time.Since(nowTime), nil) }()

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.rpc.ModelEngineAdapter.Chat",
		"req":  req,
	})

	content, usage, modelName, err := a.innerChat(ctx, &domainModel.Context{
		Prompt: lo.Must(lo.Last(req.Messages)).Content,
		RecentMessages: lo.Map(req.Messages[:len(req.Messages)-1], func(message *dto.ChatRequestMessage, _ int) *domainModel.Message {
			return &domainModel.Message{
				Role:    toDomainRole(message.Role),
				Content: message.Content,
			}
		}),
		AIProfile: req.AIProfile,
	}, req.ModelName)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to call model engine")
		return nil, err
	}
	return &dto.ChatResponse{
		ModelName: modelName,
		Content:   content,
		Usage: &dto.ChatResponseUsage{
			InputTokenCount:  usage.InputTokenCount,
			OutputTokenCount: usage.OutputTokenCount,
		},
	}, nil
}

func (a ModelEngineRPC) StreamChat(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse] {
	haloSpan := halo.NewHalo(ctx, "AISP_ModelEngineRPC_StreamChat", req.ModelName)
	haloFTSpan := halo.NewHalo(ctx, "AISP_ModelEngineRPC_StreamChat_FirstToken", req.ModelName)
	isFirstToken := true
	nowTime := time.Now()

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.rpc.ModelEngineAdapter.StreamChat",
		"req":  req,
	})

	ret := make(chan util.Progress[*dto.ChatResponse])

	utils.SafelyGo(func() {
		defer close(ret)
		defer func() { haloSpan.EndWithContext(ctx, time.Since(nowTime), nil) }()

		defer func() {
			if err := recover(); err != nil {
				logger.WithField(ctx, "err", err).Error(ctx, "panic in StreamChat")
				ret <- util.Progress[*dto.ChatResponse]{E: fmt.Errorf("%v", err)}
			}
		}()

		resultStream := a.innerStreamChat(ctx, &domainModel.Context{
			Prompt: lo.Must(lo.Last(req.Messages)).Content,
			RecentMessages: lo.Map(req.Messages[:len(req.Messages)-1], func(message *dto.ChatRequestMessage, _ int) *domainModel.Message {
				return &domainModel.Message{
					Role:    toDomainRole(message.Role),
					Content: message.Content,
				}
			}),
			AIProfile: req.AIProfile,
		}, req.ModelName)

		for progress := range resultStream {
			if progress.E != nil {
				ret <- util.Progress[*dto.ChatResponse]{E: progress.E}
				logger.WithError(ctx, progress.E).Error(ctx, "failed to call model engine")
				return
			}
			ret <- util.Progress[*dto.ChatResponse]{V: &dto.ChatResponse{
				ModelName: req.ModelName,
				Content:   progress.V.Content,
				Usage: &dto.ChatResponseUsage{
					InputTokenCount:  progress.V.Usage.InputTokenCount,
					OutputTokenCount: progress.V.Usage.OutputTokenCount,
				},
			}}
			if isFirstToken {
				haloFTSpan.EndWithContext(ctx, time.Since(nowTime), nil)
				isFirstToken = false
			}
		}
		return
	}, func(_ error) {})
	return ret
}
