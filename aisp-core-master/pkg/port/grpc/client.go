package grpc

import (
	"context"

	"google.golang.org/grpc"
)

var DialContext func(ctx context.Context, target string, opts ...grpc.DialOption) (grpc.ClientConnInterface, error)
