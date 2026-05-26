package dao

import (
	"context"
	"time"
)

type LogicSessionCacheDao[T any] interface {
	SaveCache(ctx context.Context, scene string, logicName string, sessionId int64, items *T) error
	GetCache(ctx context.Context, scene string, logicName string, sessionId int64) (*T, error)
	RemoveCache(ctx context.Context, scene string, logicName string, sessionId int64) error
}

// SessionCacheTTL 逻辑缓存的过期时间
const SessionCacheTTL = 2190 * time.Hour

// CacheData 存放在redis/其他存储源 中的结构体 用于系列化各种类型
type CacheData[T any] struct {
	Data *T `json:"data"`
}
