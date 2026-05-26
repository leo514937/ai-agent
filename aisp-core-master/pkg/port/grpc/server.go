package grpc

import (
	"github.com/grpc-ecosystem/grpc-gateway/v2/runtime"
	"google.golang.org/grpc"
)

type Server interface {
	grpc.ServiceRegistrar

	Run() error
}

type HTTPServer interface {
	Mux() *runtime.ServeMux
	Run() error
}

var (
	NewGRPCServer     func(name, listenAddr string) Server
	NewGRPCHTTPServer func(name, listenAddr string) HTTPServer
)
