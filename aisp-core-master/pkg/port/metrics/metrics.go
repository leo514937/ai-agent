package metrics

import (
	"context"
	"time"
)

type Client interface {
	Count(ctx context.Context, key string, value int64)
	Gauge(ctx context.Context, key string, value float64)
	Timing(ctx context.Context, key string, value time.Duration)
	IncrError(ctx context.Context, name string)
	IncrErrorF(ctx context.Context, format string, args ...interface{})
	Incr(ctx context.Context, name string)
	IncrF(ctx context.Context, format string, args ...interface{})
	T(ctx context.Context, key string) T
}

type T interface {
	Submit()
}

var NewClient func(name string) Client
