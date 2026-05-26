package dao

import "context"

// SiteLevelDao 获取网站等级
type SiteLevelDao interface {
	// GetLevelWithDefault 批量获取多个url的level，支持泛型默认值
	GetLevelWithDefault(ctx context.Context, defaultValue int, keys ...string) (map[string]int, error)
}
