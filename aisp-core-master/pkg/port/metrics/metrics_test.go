package metrics

import (
	"context"
	"time"
)

type DummyClient struct{}

func (c DummyClient) IncrError(ctx context.Context, name string) {}

func (c DummyClient) IncrErrorF(ctx context.Context, format string, args ...interface{}) {}

func (c DummyClient) Incr(ctx context.Context, name string) {}

func (c DummyClient) IncrF(ctx context.Context, format string, args ...interface{}) {}

func (DummyClient) Count(ctx context.Context, key string, value int64) {}

func (DummyClient) Gauge(ctx context.Context, key string, value float64) {}

func (DummyClient) Timing(ctx context.Context, key string, value time.Duration) {}

func (DummyClient) T(ctx context.Context, key string) T { return DummyT{} }

var _ Client = (*DummyClient)(nil)

type DummyT struct{}

func (DummyT) Submit() {}

var _ T = DummyT{}

func init() {
	NewClient = func(name string) Client {
		return &DummyClient{}
	}
}
