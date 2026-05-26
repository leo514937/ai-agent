package mcp_server

import (
	"flag"

	"git.in.zhihu.com/go/cafe"
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/mcpserver"
)

func Main() {
	port := flag.Int("port", 8000, "port to listen")

	handler := mcpserver.Handler()

	app := cafe.NewApplication(
		cafe.WithProfiler(6060),
	)
	app.AddBundle(rest.New(
		rest.WithRouter(handler),
		rest.Port(*port),
		rest.Timeout(0),
		rest.ReadTimeout(0),
		rest.WriteTimeout(0),
	))
	app.Run()
}
