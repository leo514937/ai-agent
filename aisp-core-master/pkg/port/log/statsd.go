package log

import (
	"context"

	"git.in.zhihu.com/go/box/statsd"
	"github.com/spf13/cast"
)

func StatsdChatSchema(ctx context.Context, schema string) {
	scene := GetSceneFromContext(ctx)
	bucket := "aisp-core.scene." + scene + ".chat.schema." + schema
	statsd.Increment(bucket)
}

func StatsdRecall(ctx context.Context, source string, stage string, count int) {
	scene := GetSceneFromContext(ctx)
	bucket := "aisp-core.scene." + scene + ".recall.source." + source + ".stage." + stage
	Infof(ctx, "StatsdRecall bucket:%s, count:%d", bucket, count)
	statsd.RecordTime(bucket, int64(count))

	if count == 0 {
		bucket = "aisp-core.scene." + scene + ".recall.empty." + source + ".stage." + stage
		statsd.Increment(bucket)
	}
}

func StatsdCheckItem(ctx context.Context, op string, isPass bool) {
	scene := GetSceneFromContext(ctx)
	bucket := "aisp-core.scene." + scene + ".check.item." + op + ".is_pass."
	Infof(ctx, "StatsdCheckItem bucket:%s%v", bucket, isPass)
	statsd.Increment(bucket + cast.ToString(isPass))
	statsd.Increment(bucket + "all")
}

func StatsdError(ctx context.Context, op string, modelName string, err string) {
	scene := GetSceneFromContext(ctx)

	prefix := "aisp-core.scene." + scene + ".modelapi." + op + ".model." + modelName + ".error."

	statsd.Increment(prefix + "all")
	statsd.Increment(prefix + err)
}
