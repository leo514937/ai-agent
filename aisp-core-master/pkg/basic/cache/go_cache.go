package cache

import (
	"time"

	goCache "github.com/patrickmn/go-cache"
)

// 与 safe_cache 不同的是：
// 1、只用内存缓存，不用 redis 缓存
// 2、手动 set 缓存，不会在 get 为空时读取外部服务并写入缓存
// 3、没有上限和 lru 机制，适用于轻量级内存缓存场景，适用于离线脚本
type CacheClient struct {
	cache *goCache.Cache
}

var DefaultCacheClient *CacheClient

func init() {
	DefaultCacheClient = NewCacheClient(10*time.Minute, 10*time.Minute)
}

func NewCacheClient(defaultExpiration time.Duration, cleanupInterval time.Duration) *CacheClient {
	return &CacheClient{
		cache: goCache.New(defaultExpiration, cleanupInterval),
	}
}

func (c *CacheClient) Set(key string, value interface{}, expiration time.Duration) {
	c.cache.Set(key, value, expiration)
}

func (c *CacheClient) Get(key string) (interface{}, bool) {
	return c.cache.Get(key)
}
