package halo

import (
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
)

type ServerSpan struct {
	Client  statsd.Client
	Service string
	Method  string
}

func (s *ServerSpan) End(elapsed time.Duration, input Error) {
	s.Client.Increment(s.Count())

	if input != nil && !input.IsCanceled() {
		s.Client.Increment(s.Error(input))
	}

	s.Client.Timing(s.Timing(), elapsed)
}

func (s *ServerSpan) Timing() string {
	return s.withSuffix("request_time")
}

func (s *ServerSpan) Count() string {
	return s.withSuffix("count")
}

func (s *ServerSpan) Error(err Error) string {
	return s.withSuffix("error", statsd.Node(err.Class()), "count")
}

func (s *ServerSpan) withSuffix(suffix ...string) string {
	return statsd.Join(
		statsd.Node(s.Service),
		"_all",
		"server",
		statsd.Node(s.Method),
		statsd.Join(suffix...),
	)
}
