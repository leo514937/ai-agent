package model

import (
	"time"
)

// LogicSessionCache 逻辑算子session缓存
type LogicSessionCache struct {
	ID         int64     `json:"id" borm:"primary_key"`
	CacheKey   string    `json:"cache_key"`                  // Key
	CacheValue string    `json:"cache_value"`                // Value
	ExpireTime time.Time `json:"expire_time"`                // 过期时间
	CreatedAt  time.Time `json:"created_at" borm:"readonly"` // 创建时间 设置borm只读，利用数据库的能力生成 CreatedAt
	UpdatedAt  time.Time `json:"updated_at" borm:"readonly"` // 修改时间 设置borm只读，利用数据库的能力生成 CreatedAt
}
