package log

import (
	"context"
	"encoding/json"
	"time"

	"git.in.zhihu.com/go/base/telemetry"
	"git.in.zhihu.com/go/base/telemetry/statsd"
	opentracing "github.com/opentracing/opentracing-go"
	"github.com/opentracing/opentracing-go/log"
)

type SpanLogger struct {
	op            string
	tags          map[string]any
	span          opentracing.Span
	beginTime     time.Time // 请求开始时间
	startTime     time.Time // span 开始时间
	scene         string
	trafficSource string
}

type Field = log.Field
type Tags map[string]any

func StartChildSpanWithContext(ctx context.Context, op string, opts ...Tags) (*SpanLogger, context.Context, context.Context) {
	opentracingOpts := make([]opentracing.StartSpanOption, 0)

	tags := make(map[string]any)
	for _, opt := range opts {
		tags = opt
		opentracingOpts = append(opentracingOpts, opentracing.Tags(tags))
	}

	span, ctx1 := telemetry.StartChildSpanWithContext(ctx, op, opentracingOpts...)
	beginTime := GetBeginTimeFromContext(ctx1)
	startTime := time.Now()
	scene := GetSceneFromContext(ctx1)
	trafficSource := GetTrafficSourceFromContext(ctx1)

	s := &SpanLogger{
		op:            op,
		tags:          tags,
		span:          span,
		beginTime:     beginTime,
		startTime:     startTime,
		scene:         scene,
		trafficSource: trafficSource,
	}

	statsd.Timing("aisp-core.scene."+s.scene+".traffic."+s.trafficSource+".span."+s.op+".start.time", time.Since(s.beginTime))

	return s, ctx1, ctx
}

func (s *SpanLogger) Finish() {
	if s != nil {
		statsd.Timing("aisp-core.scene."+s.scene+".traffic."+s.trafficSource+".span."+s.op+".process.time", time.Since(s.startTime))
		statsd.Timing("aisp-core.scene."+s.scene+".traffic."+s.trafficSource+".span."+s.op+".finish.time", time.Since(s.beginTime))

		if s.span != nil {
			s.span.Finish()
		}
	}
}

func (s *SpanLogger) LogFields(fields ...Field) {
	if s != nil && s.span != nil {
		s.span.LogFields(fields...)
	}
}

func Message(val string) Field {
	return log.Message(val)
}

func String(key string, val string) Field {
	return log.String(key, val)
}

func OmittedString(key string, val string) Field {
	return log.String(key, Omit(val))
}

func Int64(key string, val int64) Field {
	return log.Int64(key, val)
}

// 获取 json 忽略错误，主要用于 pb 调试
func getJSONIgnoreError(v interface{}) string {
	s, _ := json.Marshal(v)
	return string(s)
}

func Json(key string, val any) Field {
	return log.String(key, getJSONIgnoreError(val))
}

func ErrorField(err error) Field {
	return log.Error(err)
}

func Object(key string, val any) Field {
	return log.Object(key, val)
}

func Omit(text string) string {
	n := 90
	halfN := (n / 2) - 3

	if len(text) <= n {
		return text
	}

	textPrefix := text[:halfN]
	textSuffix := text[len(text)-halfN:]

	return textPrefix + "......" + textSuffix
}
