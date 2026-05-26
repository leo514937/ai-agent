package resource

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"git.in.zhihu.com/zrec/zrec-utils/cache/manager"
	"git.in.zhihu.com/zrec/zrec-utils/redis/impl"
)

var RedisRateLimiter redis.Client
var RedisSequence redis.Client
var RedisByIdGenerator redis.Client
var RedisBySafeCache redis.Client
var RedisByPrompt redis.Client
var RedisByPrefabWord redis.Client
var RedisByRelatedWord redis.Client
var RedisByRelatedWordRecall redis.Client
var RedisByChunkEmbedding redis.Client
var RedisByAIDaily redis.Client
var RedisByOutSiteRecall redis.Client
var RedisLocalCache *manager.RedisLocalCache
var ZhiDaSkuRedisLocalCache *manager.RedisLocalCache

func init() {
	RedisRateLimiter = redis.NewClient("ratelimiter")
	RedisSequence = redis.NewClient("sequence")
	RedisByIdGenerator = redis.NewClient("id_generator")
	RedisBySafeCache = redis.NewClient("safe_cache")
	RedisByPrompt = redis.NewClient("prompt_cache")
	RedisByPrefabWord = redis.NewClient("prefab_word_cache")
	RedisByRelatedWord = redis.NewClient("related_word_cache")
	RedisByRelatedWordRecall = redis.NewClient("related_word_cache_recall")
	RedisByChunkEmbedding = redis.NewClient("chunk_embedding")
	RedisByAIDaily = redis.NewClient("ai_daily")
	RedisByOutSiteRecall = redis.NewClient("outsite_level")
	ZhiDaSkuRedisLocalCache = manager.NewRedisLocalCache(impl.NewBaseRedisImpl(redis.AispCoreZhiDaSkuRedis))
	RedisLocalCache = manager.NewRedisLocalCache(impl.NewBaseRedisImpl(redis.AispCoreRedis))
}
