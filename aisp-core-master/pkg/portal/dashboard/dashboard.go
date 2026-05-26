package dashboard

import httpport "git.in.zhihu.com/zhihu/aisp-core/pkg/port/http"

var (
	RegisterAispCoreDashboardHTTPServer func(httpport.Server)
)
