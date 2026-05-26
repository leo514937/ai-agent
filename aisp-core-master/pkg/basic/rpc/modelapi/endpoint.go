package modelapi

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

type ModelTarget interface {
	GenerateImage(ctx context.Context, req *dto.GenerateImageRequest) (*dto.GenerateImageResponse, error)
	Chat(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error)
	Responses(ctx context.Context, req *dto.ChatRequest) (*dto.ChatResponse, error)
	StreamChat(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse]
	StreamResponses(ctx context.Context, req *dto.ChatRequest) <-chan util.Progress[*dto.ChatResponse]
}
