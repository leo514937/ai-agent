package main

import (
	"context"
	"fmt"
	"sync"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/cache"
)

func main() {
	a := 100
	b := 50

	group := sync.WaitGroup{}
	group.Add(a + b)
	TestCache1(a, &group)
	fmt.Println("-------------------------")
	TestCache2(b, &group)
	group.Wait()
}

func TestCache1(count int, group *sync.WaitGroup) {
	safeCache := cache.NewSafeCache(&cache.SafeCacheConfig{
		DefCacheTimeOut: 600,
	})

	fmt.Println("准备TestCache1")
	for i := 0; i < count; i++ {
		defer group.Done()
		go func(index int) {
			c, b := safeCache.GetCache(context.Background(), "222111", func(c context.Context, k string) (string, error) {
				fmt.Println("Test2 穿透查询")
				return "hello cache", nil
			})
			if b {
				fmt.Println("TestCache1 => ", c)
			} else {
				fmt.Println("TestCache1 未命中查询")
			}
		}(i)
	}
}

func TestCache2(count int, group *sync.WaitGroup) {
	safeCache := cache.NewSafeCache(&cache.SafeCacheConfig{
		DefCacheTimeOut: 600,
	})

	fmt.Println("准备TestCache2")
	for i := 0; i < count; i++ {
		go func(index int) {
			defer group.Done()
			c, b := safeCache.GetCache(context.Background(), "2221121", func(c context.Context, k string) (string, error) {
				fmt.Println("返回空数据")
				return "", nil
			})
			if b {
				fmt.Println("TestCache2 =>", c)
			} else {
				fmt.Println("TestCache2 未命中查询")
			}
		}(i)
	}
}
