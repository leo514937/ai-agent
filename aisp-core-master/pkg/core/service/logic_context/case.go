package logic_context

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

func InitLogicContext(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	logicName string, op string, opts ...log.Tags) (*log.SpanLogger, context.Context, context.Context, interface{}) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, op, opts...)
	ctx = log.ContextWithAB(ctx, requestCtx.GetBizContext().GetAbParamValueStrSlice())
	ctx = log.ContextWithClientSource(ctx, requestCtx.GetBizContext().RequestHeader().GetClientSource())
	ctx = log.ContextWithTrafficSource(ctx, requestCtx.GetBizContext().RequestHeader().GetTrafficSource())
	ctx = log.ContextWithTrafficReference(ctx, requestCtx.GetBizContext().RequestHeader().GetTrafficReference())

	if requestCtx.GetBizContext().GetRunCaseConfig().IsOpen &&
		!requestCtx.GetBizContext().GetRunCaseConfig().IsBase &&
		!util.StringInSlice(logicName, requestCtx.GetBizContext().GetRunCaseConfig().AffectedLogics) {
		// 读缓存
		cacheResp, exist := cache.DefaultCacheClient.Get(logicName)
		if exist {
			return span, ctx, logCtx, cacheResp
		}
	}

	return span, ctx, logCtx, nil
}

func DeferContext[T any](span *log.SpanLogger, logicName string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], logicResponse *T) {
	span.Finish()
	if requestCtx.GetBizContext().GetRunCaseConfig().IsOpen && requestCtx.GetBizContext().GetRunCaseConfig().IsBase {
		// 写缓存
		cache.DefaultCacheClient.Set(logicName, *logicResponse, 10*time.Minute)
	}
}
