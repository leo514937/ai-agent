package recall_grpc_service

import (
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	grpcport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc"
)

func Main() {
	server := grpcport.NewGRPCServer("aisp-core-grpc-recall-service", ":9999")
	resources.Init(graph_constant.ApiRecall)
	grpc.RegisterAispRecallServiceServer(server)
	err := server.Run()
	utils.PanicIf(err)
}
