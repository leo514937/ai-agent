package zhihaitu_web

import (
	"flag"
	"os"

	httpport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/http"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/zhihaitu"
)

func Main(argsIndex int) {

	var port = flag.Int("port", 9997, "port to listen")

	_ = flag.CommandLine.Parse(os.Args[argsIndex:])

	server := httpport.NewServer("zhihaitu-web", *port)
	zhihaitu.RegisterZhihaituHTTPServer(server)
	err := server.Run()
	if err != nil {
		panic(err)
	}
}
