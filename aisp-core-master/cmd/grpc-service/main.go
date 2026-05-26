package grpc_service

import (
	"context"
	"flag"
	"os"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	grpcport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc"
)

func Main(argsIndex int) {
	var sceneName string
	flag.StringVar(&sceneName, "scene", graph_constant.ApiStreamChat, "which Scene Want Run")

	_ = flag.CommandLine.Parse(os.Args[argsIndex:])

	log.Infof(context.Background(), "resources.Init sceneName: %s", sceneName)
	resources.Init(sceneName)

	server := grpcport.NewGRPCServer("aisp-core-grpc-service", ":9999")
	grpc.RegisterAispChatServiceServer(server)
	err := server.Run()
	utils.PanicIf(err)
}
