package grpc_web

import (
	grpcport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc"
)

func Main() {
	server := grpcport.NewGRPCHTTPServer("aisp-core-grpc", ":9998")
	grpc.RegisterAispCoreServieHTTPServer(server.Mux())
	err := server.Run()
	if err != nil {
		panic(err)
	}
}
