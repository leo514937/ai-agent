package shared

import (
	"context"
	"time"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/metrics"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
)

type RateLimiter interface {
	TryAcquire(ctx context.Context, tenantID int64, taskID int64, limit int64) (bool, error)
}

var DefaultRateLimiter RateLimiter

type RedisSlidingWindowRateLimiter struct {
	redisClient redis.Client
	deltaMillis int64

	metricsClient metrics.Client
}

func (l *RedisSlidingWindowRateLimiter) generateKey(tenantID int64, taskID int64) string {
	return "sliding_window_rate_limiter:" + utils.Int64ToStr(tenantID) + ":" + utils.Int64ToStr(taskID)
}

func (l *RedisSlidingWindowRateLimiter) TryAcquire(ctx context.Context, tenantID int64, taskID int64, limit int64) (bool, error) {
	// 用 utils.Now 方便测试
	nowMillis := util.TimeUnixMilli()
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenantID":  tenantID,
		"taskID":    taskID,
		"limit":     limit,
		"nowMillis": nowMillis,
	})
	l.metricsClient.Count(ctx, "acquire", 1)
	l.metricsClient.Gauge(ctx, "limit", float64(limit))

	key := l.generateKey(tenantID, taskID)
	result := l.redisClient.ZCount(ctx, key, utils.Int64ToStr(nowMillis-l.deltaMillis), utils.Int64ToStr(nowMillis))
	if err := result.Err(); err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to get zcard")
		return false, err
	}

	if result.Val() >= limit {
		l.metricsClient.Count(ctx, "acquire.reject", 1)
		return false, nil
	}

	_, err := l.redisClient.Pipelined(ctx, func(pipe redis.Pipeliner) error {
		pipe.ZAdd(ctx, key, &redis.Z{Score: float64(nowMillis), Member: nowMillis})
		pipe.ZRemRangeByScore(ctx, key, "-inf", utils.Int64ToStr(nowMillis-2*l.deltaMillis))
		pipe.Expire(ctx, key, time.Second*10)
		return nil
	})
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to pipeline")
		return false, err
	}
	return true, nil
}

var _ RateLimiter = (*RedisSlidingWindowRateLimiter)(nil)

func NewRedisSlidingWindowRateLimiter() RateLimiter {
	return &RedisSlidingWindowRateLimiter{
		redisClient:   resource.RedisRateLimiter,
		deltaMillis:   1000,
		metricsClient: metrics.NewClient("business.shared.ratelimiter"),
	}
}

func init() {
	DefaultRateLimiter = NewRedisSlidingWindowRateLimiter()
}
