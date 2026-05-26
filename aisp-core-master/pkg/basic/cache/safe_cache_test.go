package cache

import (
	"context"
	"testing"
)

func TestCache1(t *testing.T) {

	safeCache := NewSafeCache(&SafeCacheConfig{
		DefCacheTimeOut: 600,
	})

	for i := 0; i < 1000; i++ {
		go func(index int) {
			cache, b := safeCache.GetCache(context.Background(), "222111", func(c context.Context, k string) (string, error) {
				t.Log("命中查询")
				return "hello cache", nil
			})
			if b {
				t.Log(cache)
			} else {
				t.Error("未命中查询")
			}
		}(i)
	}
}

func TestCache2(t *testing.T) {
	safeCache := NewSafeCache(&SafeCacheConfig{
		DefCacheTimeOut: 600,
	})

	for i := 0; i < 1000; i++ {
		go func(index int) {
			cache, b := safeCache.GetCache(context.Background(), "222111", func(c context.Context, k string) (string, error) {
				t.Log("返回空数据")
				return "", nil
			})
			if b {
				t.Log(cache)
			} else {
				t.Error("未命中查询")
			}
		}(i)
	}
}
