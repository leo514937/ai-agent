package grpc

import (
	grpcport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc"
)

func Main() {
	server := grpcport.NewGRPCServer("aisp-core-grpc", ":9999")
	grpc.RegisterAispCoreServiceServer(server)
	err := server.Run()
	if err != nil {
		panic(err)
	}
}
