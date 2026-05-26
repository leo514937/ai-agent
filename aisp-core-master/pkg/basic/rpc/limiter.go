package rpc

import (
	"context"
	"sync"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

var limiterMap = sync.Map{}

func waitModelLimiter(ctx context.Context, model string) {
	limiter, isOk := limiterMap.Load(model)
	if !isOk {
		newLimiter := util.NewDynamicRateLimiter(func() float64 {
			config := config.GetInt("model.local_rate_limit.thousandth."+model, 10000*1000)

			return float64(config) / 1000.0
		})

		limiter, isOk = limiterMap.LoadOrStore(model, newLimiter)
		if !isOk {
			return
		}

		log.Infof(ctx, "new limiter for model %s limiter: %+v", model, limiter)
	}

	rateLimiter, isTypeOk := limiter.(util.DynamicRateLimiter)
	if !isTypeOk {
		return
	}

	rateLimiter.Wait(ctx)
}
