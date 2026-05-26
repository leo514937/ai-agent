package dashboard_web

import (
	"flag"
	"os"

	httpport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/http"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/dashboard"
)

func Main(argsIndex int) {

	var port = flag.Int("port", 9997, "port to listen")

	_ = flag.CommandLine.Parse(os.Args[argsIndex:])
	server := httpport.NewServer("aisp-core-dashboard", *port)
	dashboard.RegisterAispCoreDashboardHTTPServer(server)
	err := server.Run()
	if err != nil {
		panic(err)
	}
}
