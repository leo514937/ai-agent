package grpc

import (
	"context"
	"errors"
	"net/http"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry"
	"git.in.zhihu.com/go/base/telemetry/sentry"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware"
	"git.in.zhihu.com/go/cafe/rpc"
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/grpc-ecosystem/grpc-gateway/v2/runtime"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/health"
	"google.golang.org/grpc/health/grpc_health_v1"
	"google.golang.org/grpc/keepalive"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/reflection"
	"google.golang.org/grpc/status"
)

type ZhihuServer struct {
	bundle *rpc.GRPCBundle
}

func (s *ZhihuServer) RegisterService(desc *grpc.ServiceDesc, impl interface{}) {
	s.bundle.Server.RegisterService(desc, impl)
}

func (s *ZhihuServer) Run() error {
	app := cafe.NewApplication(
		cafe.WithProfiler(6060),
	)
	app.AddBundle(s.bundle)
	app.Run()
	return nil
}

var _ Server = (*ZhihuServer)(nil)

type ServerStreamWithCtx struct {
	grpc.ServerStream
	ctx context.Context
}

func (ss *ServerStreamWithCtx) Context() context.Context {
	return ss.ctx
}

func WithServerTelemetry(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (resp interface{}, err error) {
	idx := strings.LastIndex(info.FullMethod, ".")
	if idx < 0 {
		idx = strings.LastIndex(info.FullMethod, "/")
	}
	targetMethod := statsd.Node(info.FullMethod[idx+1:])
	meta, _ := metadata.FromIncomingContext(ctx)
	meta.Set("x-b3-sampled", "1")

	txn, ctx, err := telemetry.StartTransaction(ctx, &telemetry.Transaction{
		System: telemetry.TransactiongRPC,
		Method: targetMethod,
	}, telemetry.ExtractHTTPHeaders(http.Header(meta)))
	if err != nil {
		return nil, err
	}

	sentry.Recover(func() {
		ctx = log.ContextWithBeginTime(ctx)
		resp, err = handler(ctx, req)
	}, func(e error) {
		err = e
	})

	if err != nil {
		if code := status.Code(err); code != codes.Unknown {
			err = telemetry.WrapErr(err, code.String())
		}
	}

	txn.End(ctx, telemetry.WrapErrWithUnknownClass(err))

	// 不要 wrap 返回的 grpc status.Status，会导致内部不能正确处理错误类型
	return resp, errors.Unwrap(err)
}

func WithServerTelemetryStream(srv any, ss grpc.ServerStream, info *grpc.StreamServerInfo, handler grpc.StreamHandler) error {
	idx := strings.LastIndex(info.FullMethod, ".")
	if idx < 0 {
		idx = strings.LastIndex(info.FullMethod, "/")
	}
	targetMethod := statsd.Node(info.FullMethod[idx+1:])

	ctx := ss.Context()
	meta, _ := metadata.FromIncomingContext(ctx)
	meta.Set("x-b3-sampled", "1")

	txn, ctx, err := telemetry.StartTransaction(ctx, &telemetry.Transaction{
		System: telemetry.TransactiongRPC,
		Method: targetMethod,
	}, telemetry.ExtractHTTPHeaders(http.Header(meta)))
	if err != nil {
		return err
	}

	ctx = log.ContextWithBeginTime(ctx)

	sswc := &ServerStreamWithCtx{
		ServerStream: ss,
		ctx:          ctx,
	}

	sentry.Recover(func() {
		err = handler(srv, sswc)
	}, func(e error) {
		err = e
	})

	if err != nil {
		if code := status.Code(err); code != codes.Unknown {
			err = telemetry.WrapErr(err, code.String())
		}
	}

	txn.End(ctx, telemetry.WrapErrWithUnknownClass(err))

	return errors.Unwrap(err)
}

func newServer(opts ...grpc.ServerOption) *grpc.Server {
	overwriteOpts := []grpc.ServerOption{
		grpc.KeepaliveParams(keepalive.ServerParameters{
			MaxConnectionIdle:     5 * time.Minute,
			MaxConnectionAge:      60 * time.Minute,
			MaxConnectionAgeGrace: 5 * time.Minute,
			Time:                  time.Second,
			Timeout:               30 * time.Second,
		}),
		// grpc.ChainUnaryInterceptor(tgrpc.WithServerTelemetry),
		grpc.ChainUnaryInterceptor(WithServerTelemetry),
		grpc.ChainStreamInterceptor(WithServerTelemetryStream),
	}
	opts = append(opts, overwriteOpts...)

	s := grpc.NewServer(opts...)
	reflection.Register(s)
	grpc_health_v1.RegisterHealthServer(s, health.NewServer())

	return s
}

func serverFactory() *grpc.Server {
	return newServer(grpc.ChainUnaryInterceptor(tenantIDInterceptor, taskIDInterceptor))
}

func NewZhihuServer(name, listenAddr string) *ZhihuServer {
	return &ZhihuServer{
		bundle: rpc.NewGRPCBundle(name, rpc.GRPCListen(listenAddr), rpc.GRPCServerFactory(serverFactory)),
	}
}

type ZhihuHTTPServer struct {
	bundle *rest.HTTPBundle

	mux *runtime.ServeMux
}

func (s *ZhihuHTTPServer) Mux() *runtime.ServeMux {
	return s.mux
}

func (s *ZhihuHTTPServer) Run() error {
	app := cafe.NewApplication(
		cafe.WithProfiler(6060),
	)
	app.AddBundle(s.bundle)
	app.Run()
	return nil
}

var _ HTTPServer = (*ZhihuHTTPServer)(nil)

func NewZhihuHTTPServer(name, listenAddr string) *ZhihuHTTPServer {
	mux := runtime.NewServeMux()

	router := rest.NewRouter()
	router.Use(middleware.Base)
	router.Use(middleware.RealIP)
	router.Use(middleware.CheckHealth)
	router.Use(func(handler http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.Header.Get("X-Traffic-Source") != "office" && !strings.HasPrefix(r.RemoteAddr, "183.242.254.") {
				w.WriteHeader(http.StatusForbidden)
				return
			}
			if !strings.Contains(r.URL.Path, "/tenants/120001/") { // 中科院
				w.WriteHeader(http.StatusForbidden)
				return
			}
			handler.ServeHTTP(w, r)
		})
	})
	router.Mount("/", mux)

	if len(listenAddr) == 0 {
		panic(errors.New("listenAddr is empty"))
	}
	port, err := utils.ParseInt64(listenAddr[1:])
	if err != nil {
		panic(err)
	}

	s := &ZhihuHTTPServer{
		bundle: rest.New(
			rest.Port(int(port)),
			rest.WithRouter(router),
		),
		mux: mux,
	}
	return s
}

func tenantIDInterceptor(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (interface{}, error) {
	if !strings.HasPrefix(info.FullMethod, "/luca.aisp.core.AispCoreService/") {
		return handler(ctx, req)
	}
	if req, ok := req.(interface{ GetTenantId() int64 }); ok {
		ctx = util.CtxWithTenantID(ctx, req.GetTenantId())
	}
	return handler(ctx, req)
}

func taskIDInterceptor(ctx context.Context, req interface{}, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (interface{}, error) {
	if !strings.HasPrefix(info.FullMethod, "/luca.aisp.core.AispCoreService/") {
		return handler(ctx, req)
	}
	if req, ok := req.(interface{ GetTaskId() int64 }); ok {
		ctx = util.CtxWithTaskID(ctx, req.GetTaskId())
	}
	return handler(ctx, req)
}

func init() {
	NewGRPCServer = func(name, listenAddr string) Server {
		return NewZhihuServer(name, listenAddr)
	}
	NewGRPCHTTPServer = func(name, listenAddr string) HTTPServer {
		return NewZhihuHTTPServer(name, listenAddr)
	}
}
