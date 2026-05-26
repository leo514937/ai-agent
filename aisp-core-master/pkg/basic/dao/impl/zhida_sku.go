package impl

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"git.in.zhihu.com/zrec/zrec-utils/cache/manager"
)

func NewZhiDaSkuDao() dao.ZhiDaSkuDao {
	return &ZhiDaSkuDaoImpl{
		cache: resource.ZhiDaSkuRedisLocalCache,
	}
}

type ZhiDaSkuDaoImpl struct {
	cache *manager.RedisLocalCache
}

func (z *ZhiDaSkuDaoImpl) GetSkuLinkCardIds(ctx context.Context, aliasArray []string) map[string]int64 {
	if len(aliasArray) == 0 {
		return make(map[string]int64)
	}
	resultOfflineMap := make(map[string]int64)
	resultRealTimeMap := make(map[string]int64)
	group := safe_group.NewGroupWithTimeout("GetSkuLinkCardIds", 200)
	group.Go(func() error {
		z.cache.BatchGet(ctx, aliasArray, util.StringKeyGeneratorFunc,
			func(params interface{}) interface{} {
				respMap := make(map[string]int64)
				paramKeys := params.([]string)
				for _, paramKey := range paramKeys {
					respMap[paramKey] = 0
				}
				return respMap
			}, &resultOfflineMap, util.SkuAliasKeyOption)
		return nil
	})
	group.Go(func() error {
		z.cache.BatchGet(ctx, aliasArray, util.StringKeyGeneratorFunc,
			func(params interface{}) interface{} {
				respMap := make(map[string]int64)
				paramKeys := params.([]string)
				for _, paramKey := range paramKeys {
					respMap[paramKey] = 0
				}
				return respMap
			}, &resultRealTimeMap, util.SkuAliasRealTimeKeyOption)
		return nil
	})
	_ = group.Wait()

	// 如果v == 0 则表示数据已删除
	resultMap := make(map[string]int64)
	for k, v := range resultOfflineMap {
		if v != 0 {
			resultMap[k] = v
		}
	}
	for k, v := range resultRealTimeMap {
		if v != 0 {
			resultMap[k] = v
		}
	}
	return resultMap
}
