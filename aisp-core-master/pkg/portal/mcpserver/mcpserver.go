package mcpserver

import (
	"net/http"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/mcpserver/demo"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/mcpserver/global_search"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/mcpserver/zhida"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/mcpserver/zhihu"
)

func Handler() http.Handler {
	router := rest.NewRouter()

	// router.Use(middleware.Base)
	// router.Use(middleware.RealIP)
	// router.Use(rest.DefaultRequestContext)
	router.Use(middleware.CheckHealth)
	// router.Use(middleware.PanicAsError)
	// router.Use(middleware.ZhihuCORS(strings.Split(config.GetString("origins", ""), ",")))

	demoSSE := demo.NewDemoServer("/api/mcp/demo")
	zhihuSSE := zhihu.NewZhihuServer("/api/mcp/zhihu/v1")
	globalSearchSSE := global_search.NewGlobalSearchServer("/api/mcp/global_search/v1")

	router.Handle("/api/mcp/demo/sse", demoSSE.SSEHandler())
	router.Handle("/api/mcp/demo/message", demoSSE.MessageHandler())
	router.Handle("/api/mcp/zhihu/v1/sse", zhihuSSE.SSEHandler())
	router.Handle("/api/mcp/zhihu/v1/message", zhihuSSE.MessageHandler())
	router.Handle("/api/mcp/global_search/v1/sse", globalSearchSSE.SSEHandler())
	router.Handle("/api/mcp/global_search/v1/message", globalSearchSSE.MessageHandler())

	// 添加 Streamable HTTP 端点
	router.Handle("/api/mcp/zhida/v1/stream", zhida.ZhidaHandler())

	return router
}
