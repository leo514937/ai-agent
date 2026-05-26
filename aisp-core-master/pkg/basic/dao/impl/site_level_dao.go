package impl

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"github.com/spf13/cast"
)

func NewSiteLevelDaoImpl() dao.SiteLevelDao {
	return &SiteLevelDaoImpl{
		client: resource.RedisByOutSiteRecall,
	}
}

// SiteLevelDaoImpl 网站Level
type SiteLevelDaoImpl struct {
	client redis.Client
}

// GetLevelWithDefault 批量获取多个url的level，支持泛型默认值
func (r *SiteLevelDaoImpl) GetLevelWithDefault(ctx context.Context, defaultValue int, keys ...string) (map[string]int, error) {
	if len(keys) == 0 {
		return make(map[string]int), nil
	}

	values, err := r.client.MGet(ctx, keys...).Result()
	if err != nil {
		return nil, fmt.Errorf("failed to get multiple url: %w", err)
	}

	result := make(map[string]int, len(keys))
	for i, key := range keys {
		if i < len(values) && values[i] != nil {
			convertedValue, iErr := cast.ToIntE(values[i])
			if iErr != nil {
				result[key] = defaultValue
			} else {
				result[key] = convertedValue
			}
		} else {
			result[key] = defaultValue
		}
	}
	return result, nil
}
