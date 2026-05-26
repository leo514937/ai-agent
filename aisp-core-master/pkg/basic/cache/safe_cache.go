package cache

import (
	"context"
	"math/rand"
	"sync"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"github.com/hashicorp/golang-lru/v2/expirable"
)

const (
	// cachePrefixKv 缓存前缀
	cachePrefixKv string = "safe_cache:kv:"
)

type SafeCacheConfig struct {
	// DefCacheTimeOut 默认过期缓存时间(秒)
	DefCacheTimeOut int64
}

type SafeCache struct {
	Config      *SafeCacheConfig
	redisClient *redis.Client

	// 本地锁 用于 DCL 存储数据到 Redis
	lock *sync.Mutex
	// 本地缓存 用于存储伪布隆，防止过多请求穿透到数据库 (默认10秒)
	lru *expirable.LRU[string, string]
}

func NewSafeCache(config *SafeCacheConfig) *SafeCache {
	return &SafeCache{
		Config:      config,
		redisClient: &resource.RedisBySafeCache,
		lock:        &sync.Mutex{},
		lru:         expirable.NewLRU[string, string](1024, nil, time.Second*10),
	}
}

var DefSafeCache *SafeCache

// GetCache 获取缓存
func (c *SafeCache) GetCache(
	ctx context.Context, key string, callback func(c context.Context, k string) (string, error)) (
	string, bool) {
	logger := log.WithField(ctx, "getSafeCache", key)

	if key == "" || callback == nil {
		logger.Warnf(ctx, "GetCache 异常 => key 或 callback 为空")
		return "", false
	}

	// 如果有本地缓存 则表示只有有命中 无缓存问题 本次直接退出
	if _, ok := c.lru.Get(key); ok {
		logger.Warnf(ctx, "GetCache 异常 => 本地过滤器存在为空记录，请%s秒后再试", "10")
		return "", false
	}

	// 如果有查到缓存 直接返回
	if cache, cacheFlag, _ := c.getRedisCache(ctx, key, logger); cacheFlag {
		return cache, true
	}

	// 上锁 防止其他协程 抢先执行
	tryLock := c.lock.TryLock()
	defer func() {
		if tryLock {
			c.lock.Unlock()
		}
	}()

	// DCL 如果有本地缓存 则表示只有有命中 无缓存问题 本次直接退出
	if _, ok := c.lru.Get(key); ok {
		logger.Warnf(ctx, "GetCache 异常 => 本地过滤器存在为空记录")
		return "", false
	}

	// DCL 如果有查到缓存 直接返回
	if cache, cacheFlag, _ := c.getRedisCache(ctx, key, logger); cacheFlag {
		return cache, true
	}

	// 如果这个时候还没有 需要调用 回调方法来得到原数据
	callbackRes, callbackErr := callback(ctx, key)
	if callbackRes == "" || callbackErr != nil {
		c.lru.Add(key, "ok")
		// 输出异常日志
		if callbackErr != nil {
			logger.Errorf(ctx, "GetCache 异常 => Callback执行异常 => %s", callbackErr)
		} else {
			logger.Warnf(ctx, "GetCache 异常 => Callback返回结果为空")
		}
		return "", false
	}

	setRedisErr := c.setRedisCache(ctx, key, callbackRes)
	if setRedisErr != nil {
		logger.Errorf(ctx, "GetCache 异常 => 设置Redis异常 => %s", setRedisErr)
		return "", false
	}
	return callbackRes, true
}

// RemoveCache 移除缓存
func (c *SafeCache) RemoveCache(ctx context.Context, key string) (bool, error) {
	logger := log.WithField(ctx, "RemoveCache", key)

	err := c.delRedisCache(ctx, key)
	if err != nil {
		return false, err
	}

	// 如果有本地伪布隆 则需要删除
	if c.lru.Contains(key) {
		removeFlag := c.lru.Remove(key)
		if !removeFlag {
			logger.Errorf(ctx, "删除本地Flag锁失败 => %v", key)
		}
	}

	return true, nil
}

// setRedisCache 存入Redis 缓存
func (c *SafeCache) delRedisCache(ctx context.Context, key string) error {
	redisClient := *c.redisClient
	if err := redisClient.Del(ctx, cachePrefixKv+key).Err(); err != nil {
		return err
	}
	return nil
}

// setRedisCache 存入Redis 缓存
func (c *SafeCache) setRedisCache(ctx context.Context, key string, value string) error {
	redisClient := *c.redisClient
	// 防止出现雪崩行为 ttl 时间 默认为 2倍
	duration := generateRandomDuration(c.Config.DefCacheTimeOut, c.Config.DefCacheTimeOut<<1)
	if err := redisClient.Set(ctx, cachePrefixKv+key, value, duration).Err(); err != nil {
		return err
	}
	return nil
}

// getRedisCache 获得Redis 缓存
func (c *SafeCache) getRedisCache(ctx context.Context, key string, logger *log.ZhihuLogger) (string, bool, error) {
	redisClient := *c.redisClient
	redisResult := redisClient.Get(ctx, cachePrefixKv+key)
	// 检查键是否存在
	if redisResult.Err() == redis.ErrNil {
		//logger.Warnf(ctx, "GetCache 异常 => Key[%s] does not exist", key)
		return "", false, nil
	} else if redisResult.Err() != nil {
		logger.Errorf(ctx, "GetCache 异常 => Redis 查询异常 => %s", redisResult.Err())
		return "", false, redisResult.Err()
	} else {
		value, err := redisResult.Result()
		if err != nil {
			logger.Errorf(ctx, "GetCache 异常 => Redis 查询异常(Result) => %s", err)
			return "", false, err
		} else {
			return value, true, nil
		}
	}
}

// generateRandomDuration 生成在指定范围内的随机时间持续时间
func generateRandomDuration(min, max int64) time.Duration {
	// 生成随机数
	randomTime := rand.Int63n(max-min+1) + min
	// 创建时间类
	return time.Duration(randomTime) * time.Second
}

func init() {
	DefSafeCache = NewSafeCache(&SafeCacheConfig{
		DefCacheTimeOut: 600,
	})
}
