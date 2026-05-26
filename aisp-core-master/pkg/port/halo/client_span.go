package halo

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/telemetry"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/base/zae"
)

var (
	globalHaloClient statsd.Client
)

func init() {
	var err error
	globalHaloClient, err = statsd.New("span")
	if err != nil {
		panic(err)
	}
}

type ClientSpan struct {
	Client        statsd.Client
	SlowThreshold time.Duration
	Service       string
	Method        string
	TargetService string
	TargetMethod  string
}

func NewHalo(ctx context.Context, targetService string, targetMethod string) *ClientSpan {
	return &ClientSpan{
		Client:        globalHaloClient,
		Service:       zae.Service(),
		Method:        telemetry.MethodFromContext(ctx),
		TargetService: targetService,
		TargetMethod:  targetMethod,
	}
}

func (s *ClientSpan) End(elapsed time.Duration, input Error) {
	s.EndWithContext(context.Background(), elapsed, input)
}

func (s *ClientSpan) EndWithContext(ctx context.Context, elapsed time.Duration, input Error) {
	var tags statsd.Tags
	info := ServerInfoFromContext(ctx)
	if info.Region != "" {
		tags = statsd.Tags{
			"remote_region": info.Region,
			"region":        zae.Region(),
		}
	}

	s.Client.IncrementWithTag(s.Count(), tags)

	if input != nil && !input.IsCanceled() {
		s.Client.IncrementWithTag(s.Error(input), tags)
	}

	if s.SlowThreshold != 0 && elapsed > s.SlowThreshold {
		s.Client.IncrementWithTag(s.SlowLog(), tags)
	}

	s.Client.TimingWithTag(s.Timing(), tags, elapsed)
}

func (s *ClientSpan) Timing() string {
	return s.withSuffix("request_time")
}

func (s *ClientSpan) Count() string {
	return s.withSuffix("count")
}

func (s *ClientSpan) Error(err Error) string {
	return s.withSuffix("error", statsd.Node(err.Class()), "count")
}

func (s *ClientSpan) SlowLog() string {
	return s.withSuffix("slow", "count")
}

func (s *ClientSpan) withSuffix(suffix ...string) string {
	return statsd.Join(
		statsd.Node(s.Service),
		"_all",
		"client",
		statsd.Node(s.Method),
		statsd.Node(s.TargetService),
		"_all",
		statsd.Node(s.TargetMethod),
		statsd.Join(suffix...),
	)
}
