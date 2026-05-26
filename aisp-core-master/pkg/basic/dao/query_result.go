package dao

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
)

type QueryResultDao interface {
	SetResponseInfoByTTL(ctx context.Context, scene string, clientSource string, trafficSource string, chatModel string, ab map[string]string, query string, responseInfo *proto.ChatResponse, ttl time.Duration) error
	GetResponseInfo(ctx context.Context, scene string, clientSource string, trafficSource string, chatModel string, ab map[string]string, query string) (*proto.ChatResponse, error)
	DeleteResponseInfo(ctx context.Context, scene string, clientSource string, trafficSource string, chatModel string, ab map[string]string, query string) error
}
