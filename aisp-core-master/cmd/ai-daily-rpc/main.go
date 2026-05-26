package ai_daily_rpc

import (
	"fmt"

	"git.apache.org/thrift.git/lib/go/thrift"
	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/rpc"
	ai_daily_srv "git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/ai_daily"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/ai_daily_rpc"
)

func Main() {
	resources.InitAIDailyLogic()
	graph.InitZagDriver(graph_constant.ApiAIDailyPlaylist)

	aiDailyRecommendSrv := ai_daily_rpc.NewAiDailyRecommendServiceImpl()
	servicesMap := map[string]thrift.TProcessor{
		"AiDailyRecommendService": ai_daily_srv.NewAiDailyRecommendServiceProcessor(aiDailyRecommendSrv),
	}
	bundle := rpc.NewTZoneBundle(
		"aisp-ai-daily-rpc",
		rpc.WithTZoneServiceMap(servicesMap),
		rpc.TZoneListen(fmt.Sprintf("0.0.0.0:%d", 9999)),
	)
	app := cafe.NewApplication(cafe.SentryIncludePaths("git.in.zhihu.com/zhihu/aisp-core"))
	app.AddBundle(bundle)
	app.Run()
}
