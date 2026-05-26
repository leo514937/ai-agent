package metrics

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/base/grpc"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/base/zae"
	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/samber/lo"
)

type ZhihuClient struct {
	statsd.Client
}

const (
	tagKeyTenantID   = "tenant_id"
	tagKeyTaskID     = "task_id"
	tagKeyCallerUnit = "caller_unit"
	tagKeyUnit       = "unit"
)

func (c *ZhihuClient) Count(ctx context.Context, key string, value int64) {
	c.Client.CountWithTag(key, c.genTags(ctx), value)
}

func (c *ZhihuClient) Gauge(ctx context.Context, key string, value float64) {
	c.Client.GaugeWithTag(key, c.genTags(ctx), value)
}

func (c *ZhihuClient) Timing(ctx context.Context, key string, value time.Duration) {
	c.Client.TimingWithTag(key, c.genTags(ctx), value)
}

func (c *ZhihuClient) IncrError(ctx context.Context, name string) {
	c.Client.IncrementWithTag(fmt.Sprintf("error.%s", name), c.genTags(ctx))
}

func (c *ZhihuClient) IncrErrorF(ctx context.Context, format string, args ...interface{}) {
	c.Client.IncrementWithTag("error."+fmt.Sprintf(format, args...), c.genTags(ctx))
}

func (c *ZhihuClient) Incr(ctx context.Context, name string) {
	c.Client.IncrementWithTag(name, c.genTags(ctx))
}

func (c *ZhihuClient) IncrF(ctx context.Context, format string, args ...interface{}) {
	c.Client.IncrementWithTag(fmt.Sprintf(format, args...), c.genTags(ctx))
}

func (c *ZhihuClient) T(ctx context.Context, key string) T {
	return &zhihuT{
		client: c,
		ctx:    ctx,
		key:    key,
		begin:  time.Now(),
	}
}

type zhihuT struct {
	client *ZhihuClient
	ctx    context.Context
	key    string
	begin  time.Time
}

func (t *zhihuT) Submit() {
	t.client.Timing(t.ctx, t.key, time.Since(t.begin))
}

func (c *ZhihuClient) genTags(ctx context.Context) statsd.Tags {
	return statsd.Tags{
		tagKeyTenantID:   utils.Int64ToStr(util.TenantIDFromCtx(ctx)),
		tagKeyTaskID:     utils.Int64ToStr(util.TaskIDFromCtx(ctx)),
		tagKeyUnit:       zae.Service(),
		tagKeyCallerUnit: grpc.CallerFromContext(ctx).Service,
	}
}

func init() {
	NewClient = func(name string) Client {
		return &ZhihuClient{
			Client: lo.Must(statsd.New(fmt.Sprintf("%s.%s", zae.App(), name))),
		}
	}
}
