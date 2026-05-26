package rpc

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/user_grpc"
)

type ZaiRecallGuideWordGRPC interface {
	RecallGuideWords(ctx context.Context, request *user_grpc.UserGuideWordsRequest) *user_grpc.UserGuideWordsResponse
}
