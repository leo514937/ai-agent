package util

import (
	"context"
	"strings"
	"time"

	"git.in.zhihu.com/production_backend/pier"
)

const tenantIDKey = "tenantID"

var picoClient = pier.NewPicoAPI(time.Millisecond * 500)

func CtxWithTenantID(ctx context.Context, tenantID int64) context.Context {
	return context.WithValue(ctx, tenantIDKey, tenantID)
}

func TenantIDFromCtx(ctx context.Context) int64 {
	v := ctx.Value(tenantIDKey)
	if v == nil {
		return 0
	}
	return v.(int64)
}

func CtxWithTaskID(ctx context.Context, taskID int64) context.Context {
	return context.WithValue(ctx, "taskID", taskID)
}

func TaskIDFromCtx(ctx context.Context) int64 {
	v := ctx.Value("taskID")
	if v == nil {
		return 0
	}
	return v.(int64)
}

func BuildFullImageURL(hash, imageType string) string {
	if strings.HasSuffix(hash, ".gif") {
		return picoClient.GetFullURL(hash, imageType, "gif", "", true, false)
	}

	return picoClient.GetFullURL(hash, imageType, "", "", true, false)
}
