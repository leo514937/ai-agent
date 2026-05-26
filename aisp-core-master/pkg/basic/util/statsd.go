package util

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func Increment(ctx context.Context, statsFmt string, params ...string) {
	abParams := log.GetAbParamFromContext(ctx)
	if !StringInSlice(macro.DEFAULT, abParams) {
		abParams = append(abParams, macro.DEFAULT)
	}
	for _, abParam := range abParams {
		statsd.Increment(sprintfKeyByContext(ctx, statsFmt, abParam, params...))
	}
}

func Timing(ctx context.Context, statsFmt string, value time.Duration, params ...string) {
	abParams := log.GetAbParamFromContext(ctx)
	if !StringInSlice(macro.DEFAULT, abParams) {
		abParams = append(abParams, macro.DEFAULT)
	}
	for _, abParam := range abParams {
		statsd.Timing(sprintfKeyByContext(ctx, statsFmt, abParam, params...), value)
	}
}

func TimingInMilSec(ctx context.Context, statsFmt string, value float64, params ...string) {
	abParams := log.GetAbParamFromContext(ctx)
	if !StringInSlice(macro.DEFAULT, abParams) {
		abParams = append(abParams, macro.DEFAULT)
	}
	for _, abParam := range abParams {
		statsd.TimeInMilliseconds(sprintfKeyByContext(ctx, statsFmt, abParam, params...), value)
	}
}

func sprintfKeyByContext(ctx context.Context, statsFmt string, abParam string, params ...string) string {
	return fmt.Sprintf(statsFmt, getFmtParams(
		log.GetSceneFromContext(ctx),
		log.GetClientSourceFromContext(ctx),
		log.GetTrafficSourceFromContext(ctx),
		log.GetTrafficReferenceFromContext(ctx),
		abParam, params...,
	)...)
}

func getFmtParams(
	scene string, clientSource string, trafficSource string, trafficReference string,
	abParam string, params ...string) []interface{} {

	fmtParam := []interface{}{scene, abParam, clientSource, trafficSource, trafficReference}
	for _, param := range params {
		fmtParam = append(fmtParam, param)
	}
	return fmtParam
}
