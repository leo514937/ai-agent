package resource

import "git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"

var (
	DashboardAsyncRequest redis.Client
	SessionCache          redis.Client
)

func init() {
	DashboardAsyncRequest = redis.NewClient("admin-async-request")
	SessionCache = redis.NewClient("session-cache")

}
