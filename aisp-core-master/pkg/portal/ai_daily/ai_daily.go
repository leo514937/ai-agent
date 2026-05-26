package ai_daily

import (
	"net/http"

	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/go/cafe/rest/middleware"
	"git.in.zhihu.com/go/cafe/rest/middleware/auth"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	httpport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/http"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/ai_daily/handler_ai_daily"
)

var (
	router                    = rest.NewRouter()
	RegisterAIDailyHTTPServer func(httpport.Server)
)

func init() {
	router.Use(middleware.Base)
	router.Use(middleware.RealIP)
	router.Use(middleware.ZhihuCORS([]string{"*"}))
	router.Use(middleware.CheckHealth)
	router.Use(middleware.RenderOnce)
	router.Use(middleware.PanicAsErrorWithOption(func(err error) *middleware.PanicOption {
		return &middleware.PanicOption{
			IsPanic:    false,
			StatusCode: http.StatusInternalServerError,
			Error:      "服务器内部错误",
		}
	}))
	router.Use(auth.NginxAuthentication)
	router.MountHandlers(getHandlers())
	RegisterAIDailyHTTPServer = func(server httpport.Server) {
		server.(interface{ SetHandler(handler http.Handler) }).SetHandler(router)
		resources.InitAIDailyLogic()
		graph.InitZagDriver(graph_constant.ApiAIDailyPlaylist)
	}
}

func getHandlers() map[string]rest.Handler {
	return map[string]rest.Handler{
		"/ailab/playlist/today":   handler_ai_daily.NewQueryPlaylistHandler(),   // 获取今日精选
		"/ailab/playlist/history": handler_ai_daily.NewPlaylistHistoryHandler(), // 今日精选历史记录
	}
}
