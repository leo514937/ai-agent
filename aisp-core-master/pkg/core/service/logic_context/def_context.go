package logic_context

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/cache"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

type LogicContext[V any] struct {
	bizType       string
	sessionId     int64
	logicName     string
	cacheSource   CacheSource
	op            string
	runCaseConfig entities.RunCaseConfig
	Span          *log.SpanLogger
	Ctx           context.Context
	LogCtx        context.Context
	CacheResp     *LogicContextCacheResp[V]
}

type LogicContextCacheResp[V any] struct {
	IsOk bool
	Resp V
}

type CacheSource string

const CacheSourceByRedis CacheSource = "redis"
const CacheSourceByTidb CacheSource = "tidb"

func InitLogicContextV2[V any](ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	logicName string, op string, opts ...log.Tags) *LogicContext[V] {
	return InitLogicContextV2BySource[V](ctx, requestCtx, logicName, CacheSourceByRedis, op, opts...)
}

func InitLogicContextV2BySource[V any](
	ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	logicName string,
	cacheSource CacheSource,
	op string,
	opts ...log.Tags) *LogicContext[V] {

	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, op, opts...)
	ctx = log.ContextWithAB(ctx, requestCtx.GetBizContext().GetAbParamValueStrSlice())
	ctx = log.ContextWithClientSource(ctx, requestCtx.GetBizContext().RequestHeader().GetClientSource())
	ctx = log.ContextWithTrafficSource(ctx, requestCtx.GetBizContext().RequestHeader().GetTrafficSource())
	ctx = log.ContextWithTrafficReference(ctx, requestCtx.GetBizContext().RequestHeader().GetTrafficReference())

	var cacheRespFinale = &LogicContextCacheResp[V]{IsOk: false}

	// 跑 case 优先命中缓存
	if requestCtx.GetBizContext().GetRunCaseConfig().IsOpen &&
		!requestCtx.GetBizContext().GetRunCaseConfig().IsBase &&
		!util.StringInSlice(logicName, requestCtx.GetBizContext().GetRunCaseConfig().AffectedLogics) {
		// 读缓存
		cacheRespInterface, exist := cache.DefaultCacheClient.Get(logicName)
		if exist {
			if cacheRespInterface != nil {
				cacheResp, isTypeOk := cacheRespInterface.(V)
				if isTypeOk {
					cacheRespFinale.IsOk = true
					cacheRespFinale.Resp = cacheResp
				}
			}
		}
	}

	// 读远端redis 缓存
	if requestCtx.GetBizContext().GetRunCaseConfig().IsUseSessionCache && !cacheRespFinale.IsOk {
		var sessionCacheDao dao.LogicSessionCacheDao[V]
		switch cacheSource {
		case CacheSourceByTidb:
			sessionCacheDao = impl.NewLogicSessionCacheByTiDBImpl[V]()
		default:
			sessionCacheDao = impl.NewLogicSessionCacheDao[V]()
		}
		cacheTmp, cacheErr := sessionCacheDao.GetCache(ctx, requestCtx.GetBizContext().GetBizType(), logicName, requestCtx.GetBizContext().GetSessionId())
		if cacheErr == nil {
			cacheRespFinale.IsOk = true
			cacheRespFinale.Resp = *cacheTmp
		}
	}

	return &LogicContext[V]{
		bizType:       requestCtx.GetBizContext().GetBizType(),
		sessionId:     requestCtx.GetBizContext().GetSessionId(),
		logicName:     logicName,
		cacheSource:   cacheSource,
		op:            op,
		runCaseConfig: requestCtx.GetBizContext().GetRunCaseConfig(),
		Span:          span,
		Ctx:           ctx,
		LogCtx:        logCtx,
		CacheResp:     cacheRespFinale,
	}
}

// DeferFunc 用于结束逻辑处理，写缓存等操作
// 注意 logicResponse 一定是要经过 make 出来的对象 而不是 var xxx xxx
// 否则将无法正确的写入缓存
// 示例 resp := make([]*data_frame.ItemData[entities.Item], 0)
func (l *LogicContext[V]) DeferFunc(logicResponse *V) {
	l.Span.Finish()
	if l.runCaseConfig.IsOpen && l.runCaseConfig.IsBase {
		// 写缓存
		cache.DefaultCacheClient.Set(l.logicName, *logicResponse, 10*time.Minute)
	}

	// 存储session cache
	if l.runCaseConfig.IsSaveSessionCache {
		var sessionCacheDao dao.LogicSessionCacheDao[V]
		switch l.cacheSource {
		case CacheSourceByTidb:
			sessionCacheDao = impl.NewLogicSessionCacheByTiDBImpl[V]()
		default:
			sessionCacheDao = impl.NewLogicSessionCacheDao[V]()
		}
		safe_group.SafeGo(func() error {
			ctx := context.Background()
			// 异步 写缓存
			saveCacheErr := sessionCacheDao.SaveCache(
				context.Background(),
				l.bizType,
				l.logicName,
				l.sessionId,
				logicResponse,
			)
			if saveCacheErr != nil {
				log.Errorf(ctx, "save logic session cache error, scene:%s logicName: %s sessionId:%d, errMsg:%v",
					l.bizType, l.logicName, l.sessionId, saveCacheErr)
			}
			return saveCacheErr
		}, "SaveLogicSessionCache-"+l.logicName)
	}
}
