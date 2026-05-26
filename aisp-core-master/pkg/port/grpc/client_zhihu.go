package grpc

import (
	"context"
	"strings"
	"time"

	baseGrpc "git.in.zhihu.com/go/base/grpc"
	tgrpc "git.in.zhihu.com/go/base/telemetry/integrations/grpc"
	"git.in.zhihu.com/go/base/zae"
	"google.golang.org/grpc"
	"google.golang.org/grpc/backoff"
	"google.golang.org/grpc/metadata"
)

func init() {
	DialContext = func(ctx context.Context, target string, opts ...grpc.DialOption) (grpc.ClientConnInterface, error) {
		if isDomain(ctx, target) {
			opts = append(getDefaultOpts(), opts...)
			return grpc.DialContext(ctx, target, opts...)
		}

		return baseGrpc.DialContext(ctx, target, opts...)
	}
}

func getDefaultOpts() (opts []baseGrpc.DialOption) {
	defaultOpts := []grpc.DialOption{grpc.WithConnectParams(grpc.ConnectParams{
		Backoff:           backoff.DefaultConfig,
		MinConnectTimeout: 500 * time.Millisecond,
	})}
	opts = append(defaultOpts, opts...)

	overwriteOpts := []grpc.DialOption{
		grpc.WithChainUnaryInterceptor(withClientTelemetry),
		grpc.WithInsecure(),
		grpc.WithDefaultServiceConfig(`{"loadBalancingPolicy":"round_robin"}`),
	}
	opts = append(opts, overwriteOpts...)

	return opts
}

func withClientTelemetry(ctx context.Context, method string, req, reply interface{}, cc *baseGrpc.ClientConn, invoker baseGrpc.UnaryInvoker, opts ...baseGrpc.CallOption) error {
	service := cc.Target()
	service = strings.TrimPrefix(service, "/")
	service = "GRPC_" + service
	ctx = metadata.AppendToOutgoingContext(ctx, "x-zone-origin", zae.Service(),
		"x-zone-origin-app", zae.App(),
		"x-zone-origin-unit", zae.Service(),
		"x-zone-origin-token", zae.AppToken(),
		"x-zone-origin-region", zae.Region())

	return tgrpc.WithClientTelemetry(ctx, service, method, req, reply, cc, invoker, opts...)
}

func isDomain(ctx context.Context, target string) bool {
	if target == "localhost" ||
		strings.HasPrefix(target, "localhost:") ||
		strings.Contains(target, ".") {
		return true
	}

	return false
}
