package log

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
)

const (
	beginTimeKey        = "aisp-begin-time"
	sceneKey            = "aisp-scene"
	memberIDKey         = "aisp-member-id"
	ABParamKey          = "aisp-ab-param"
	clientSourceKey     = "aisp-client-source"
	trafficSourceKey    = "aisp-traffic-source"
	trafficReferenceKey = "aisp-traffic-reference"
)

func ContextWithBeginTime(ctx context.Context) context.Context {
	ctx = context.WithValue(ctx, beginTimeKey, time.Now())
	return ctx
}

func ContextWithScene(ctx context.Context, scene string) context.Context {
	ctx = context.WithValue(ctx, sceneKey, scene)
	return ctx
}

func ContextWithMemberID(ctx context.Context, memberID int64) context.Context {
	ctx = context.WithValue(ctx, memberIDKey, memberID)
	return ctx
}

func ContextWithAB(ctx context.Context, abParam []string) context.Context {
	ctx = context.WithValue(ctx, ABParamKey, abParam)
	return ctx
}

func ContextWithClientSource(ctx context.Context, source proto.ClientSource) context.Context {
	ctx = context.WithValue(ctx, clientSourceKey, source.String())
	return ctx
}

func ContextWithTrafficSource(ctx context.Context, source proto.TrafficSource) context.Context {
	ctx = context.WithValue(ctx, trafficSourceKey, source.String())
	return ctx
}

func ContextWithTrafficReference(ctx context.Context, source proto.TrafficSource) context.Context {
	ctx = context.WithValue(ctx, trafficReferenceKey, source.String())
	return ctx
}

func GetBeginTimeFromContext(ctx context.Context) time.Time {
	startTime, isOk := ctx.Value(beginTimeKey).(time.Time)
	if !isOk {
		startTime = time.Now()
	}

	return startTime
}

func GetSceneFromContext(ctx context.Context) string {
	startTime, isOk := ctx.Value(sceneKey).(string)
	if !isOk {
		startTime = "default.scene"
	}

	return startTime
}

func GetClientSourceFromContext(ctx context.Context) string {
	startTime, isOk := ctx.Value(clientSourceKey).(string)
	if !isOk {
		startTime = proto.ClientSource_UNDEFINED_SOURCE.String()
	}
	return startTime
}

func GetTrafficSourceFromContext(ctx context.Context) string {
	startTime, isOk := ctx.Value(trafficSourceKey).(string)
	if !isOk {
		startTime = proto.TrafficSource_undefined_traffic.String()
	}
	return startTime
}

func GetTrafficReferenceFromContext(ctx context.Context) string {
	startTime, isOk := ctx.Value(trafficReferenceKey).(string)
	if !isOk {
		startTime = proto.TrafficSource_undefined_traffic.String()
	}
	return startTime
}

func GetMemberIDFromContext(ctx context.Context) int64 {
	memberID, isOk := ctx.Value(memberIDKey).(int64)
	if !isOk {
		memberID = 0
	}

	return memberID
}

func GetAbParamFromContext(ctx context.Context) []string {
	result, isOk := ctx.Value(ABParamKey).([]string)
	if !isOk {
		result = []string{}
	}

	return result
}
