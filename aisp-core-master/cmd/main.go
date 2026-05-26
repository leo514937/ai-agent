package main

import (
	"context"
	"os"

	ai_daily_rpc "git.in.zhihu.com/zhihu/aisp-core/cmd/ai-daily-rpc"
	ai_daily_web "git.in.zhihu.com/zhihu/aisp-core/cmd/ai-daily-web"
	arenaworker "git.in.zhihu.com/zhihu/aisp-core/cmd/arena-worker"
	biz_grpc_service "git.in.zhihu.com/zhihu/aisp-core/cmd/biz-grpc-service"
	crawler_webpage "git.in.zhihu.com/zhihu/aisp-core/cmd/crawler-webpage"
	dashboardweb "git.in.zhihu.com/zhihu/aisp-core/cmd/dashboard-web"
	"git.in.zhihu.com/zhihu/aisp-core/cmd/grpc"
	grpcservice "git.in.zhihu.com/zhihu/aisp-core/cmd/grpc-service"
	grpcweb "git.in.zhihu.com/zhihu/aisp-core/cmd/grpc-web"
	mcp_server "git.in.zhihu.com/zhihu/aisp-core/cmd/mcp-server"
	"git.in.zhihu.com/zhihu/aisp-core/cmd/offline"
	recall_grpc_service "git.in.zhihu.com/zhihu/aisp-core/cmd/recall-grpc-service"
	rpccensor "git.in.zhihu.com/zhihu/aisp-core/cmd/rpc-censor"
	translate_grpc_service "git.in.zhihu.com/zhihu/aisp-core/cmd/translate-grpc-service"
	zhihaituweb "git.in.zhihu.com/zhihu/aisp-core/cmd/zhihaitu-web"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {

	service := os.Args[1]
	log.Infof(context.Background(), "args: %v", os.Args)
	switch service {
	case "grpc":
		// 启动命令 ./bin/main grpc
		// 启动命令 go run cmd/main.go grpc
		log.Info(context.Background(), "run grpc.Main")
		grpc.Main()
	case "grpc-web":
		// 启动命令 ./bin/main grpc-web
		// 启动命令 go run cmd/main.go grpc-web
		log.Info(context.Background(), "run grpcweb.Main")
		grpcweb.Main()
	case "grpc-service":
		// 启动命令 ./bin/main grpc-service --port=xxx
		// 启动命令 go run cmd/main.go grpc-service --port=xxx
		log.Info(context.Background(), "run grpcservice.Main")
		grpcservice.Main(2)
	case "biz-grpc-service":
		// 启动命令 ./bin/main biz-grpc-service --port=xxx
		// 启动命令 go run cmd/main.go biz-grpc-service --port=xxx
		log.Info(context.Background(), "run bizgrpcservice.Main")
		biz_grpc_service.Main()
	case "recall-grpc-service":
		// 启动命令 ./bin/main recall-service --port=xxx
		// 启动命令 go run cmd/main.go recall-service --port=xxx
		log.Info(context.Background(), "run recallgrpcservice.Main")
		recall_grpc_service.Main()
	case "translate-grpc-service":
		// 启动命令 ./bin/main translate-grpc-service --port=xxx
		// 启动命令 go run cmd/main.go translate-grpc-service --port=xxx
		log.Info(context.Background(), "run translategrpcservice.Main")
		translate_grpc_service.Main()
	case "crawler-webpage":
		// 启动命令 ./bin/main crawler-webpage --port=xxx
		// 启动命令 go run cmd/main.go crawler-webpage --port=xxx
		log.Info(context.Background(), "run crawler_webpage.Main")
		crawler_webpage.Main()
	case "dashboard-web":
		// 启动命令 ./bin/main dashboard-web --port=xxx
		// 启动命令 go run cmd/main.go dashboard-web --port=xxx
		log.Info(context.Background(), "run dashboardweb.Main")
		dashboardweb.Main(2)
	case "zhihaitu-web":
		// 启动命令 ./bin/main zhihaitu-web --port=xxx
		// 启动命令 go run cmd/main.go zhihaitu-web --port=xxx
		log.Info(context.Background(), "run zhihaituweb.Main")
		zhihaituweb.Main(2)
	case "arena-worker":
		// 启动命令 ./bin/main arena-worker
		// 启动命令 go run cmd/main.go arena-worker
		log.Info(context.Background(), "run arenaworker.Main")
		arenaworker.Main()
	case "rpc-censor":
		// 启动命令 ./bin/main rpc-censor
		// 启动命令 go run cmd/main.go rpc-censor
		log.Info(context.Background(), "run rpccensor.Main")
		rpccensor.Main()
	case "offline":
		// 启动命令 ./bin/main offline
		// 启动命令 go run cmd/main.go offline
		log.Info(context.Background(), "run offline.Main")
		offline.Main(2)
	case "ai-daily-web":
		// 启动命令 ./bin/main ai-daily-web
		// 启动命令 go run cmd/main.go ai-daily-web
		log.Info(context.Background(), "run ai-daily-web.Main")
		ai_daily_web.Main()
	case "ai-daily-rpc":
		// 启动命令 ./bin/main ai-daily-rpc
		// 启动命令 go run cmd/main.go ai-daily-rpc
		log.Info(context.Background(), "run ai-daily-rpc.Main")
		ai_daily_rpc.Main()
	case "mcp-server":
		// 启动命令 ./bin/main mcp-server
		// 启动命令 go run cmd/main.go mcp-server
		log.Info(context.Background(), "run mcp-server.Main")
		mcp_server.Main()
	}
	log.Info(context.Background(), "shut down !!!")
}
