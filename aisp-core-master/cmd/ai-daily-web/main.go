package ai_daily_web

import (
	"flag"

	httpport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/http"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/ai_daily"
)

func Main() {
	var port = flag.Int("port", 9997, "port to listen")
	server := httpport.NewServer("ai-daily-web", *port)
	ai_daily.RegisterAIDailyHTTPServer(server)
	err := server.Run()
	if err != nil {
		panic(err)
	}
}
