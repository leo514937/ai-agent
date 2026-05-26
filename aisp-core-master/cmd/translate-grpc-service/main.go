package translate_grpc_service

import (
	"git.in.zhihu.com/go/utils"
	grpcport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc"
)

func Main() {
	server := grpcport.NewGRPCServer("aisp-translate-service", ":9999")
	grpc.RegisterAispTranslateServiceServer(server)
	err := server.Run()
	utils.PanicIf(err)
}
