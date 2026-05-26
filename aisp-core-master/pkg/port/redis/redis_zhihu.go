package redis

import (
	"git.in.zhihu.com/go/base/redis"
	"github.com/samber/lo"
)

const AispCoreRedis = "aisp-core"

// 站外召回等级
const AispCoreOutSiteLevelRedis = "outsite-level"

const AispCoreZhiDaSkuRedis = "zhida-sku"

var pools = map[string]redis.Client{
	"ratelimiter":               redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"sequence":                  redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"rum_cache":                 redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"admin-async-request":       redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"session-cache":             redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"safe_cache":                redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"id_generator":              redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"prompt_cache":              redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"prefab_word_cache":         redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"related_word_cache":        redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"related_word_cache_recall": redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"chunk_embedding":           redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"ai_daily":                  redis.NewRWClient(lo.Must(redis.Discovery(AispCoreRedis))),
	"outsite_level":             redis.NewRWClient(lo.Must(redis.Discovery(AispCoreOutSiteLevelRedis))),
	"zhida_sku":                 redis.NewRWClient(lo.Must(redis.Discovery(AispCoreZhiDaSkuRedis))),
}

func NewClient(name string) redis.Client {
	pool, ok := pools[name]
	if !ok {
		panic(ErrNameNotFound)
	}
	return pool
}
