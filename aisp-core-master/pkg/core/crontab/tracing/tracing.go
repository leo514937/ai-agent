package tracing

import (
	"context"
	"time"

	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/tracing_log"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/tracing_platform"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"git.in.zhihu.com/zrec/zrec-utils/redis/impl"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"git.in.zhihu.com/zrec/zrec-utils/task"
	"git.in.zhihu.com/zrec/zrec-utils/util"
)

// badCase数据同步兜底重试，把同步中的数据捞出来，再重试一遍
func init() {
	ctx := context.TODO()

	redisClient := impl.NewBaseRedisImpl(redis.AispCoreRedis)
	periodSecond := int64(1 * util.HourSecond) // 执行周期：1hour

	safe_group.SafeGo(func() error {
		for {
			// 使用 redis 做分布式锁，每次只有一个容器执行
			_ = task.SingleTask(ctx, redisClient, badCaseTracingRetry, "badCaseTracingRetry", periodSecond)
			// 使用 2 倍频率做检测，每 30min 检测一次锁有没有释放
			<-time.After(time.Duration(periodSecond/2) * time.Second)
		}
	}, "badCaseTracingRetry panic")
}

var tracingPlatformService = service.DefaultTracingPlatformService
var tracingLogService = tracing_log.DefaultTracingLogService

func badCaseTracingRetry() error {
	ctx := context.TODO()

	badCaseList, _, _ := tracingPlatformService.ListBadCaseTracing(ctx, &model.FilterParams{State: 2})

	for _, badCase := range badCaseList {
		searchResults, err := tracingLogService.SearchRucene(ctx, &model.LogRucene{TraceId: badCase.TraceId})
		if err != nil || len(searchResults) == 0 {
			continue
		}
		requestTime := searchResults[0].RequestTimeMs
		if util2.IsMillisecond(requestTime) {
			requestTime = requestTime / 1000
		}
		err = tracingPlatformService.AddBadCaseTracingAsync(ctx, &model.BadcaseTracingFilterParams{
			TraceId:         badCase.TraceId,
			FeedbackSource:  badCase.FeedbackSource,
			CaseType:        badCase.CaseType,
			CaseDescription: badCase.CaseDescription,
			RequestTime:     util2.TimeStamp2DateTime(requestTime),
		})
		if err != nil {
			log.Errorf(ctx, "badCaseTracingRetry failed, traceId: %s, err: %v", badCase.TraceId, err)
		}
	}

	return nil
}
