package rum_cache

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type RumCache interface {

	// SaveDeleteErrorCache 保存删除错误缓存
	SaveDeleteErrorCache(ctx context.Context, id int64, rumTableName string)

	// RemoveDeleteErrorCache 保存删除错误缓存
	RemoveDeleteErrorCache(ctx context.Context, id int64, rumTableName string)

	// FilterDeleteErrorWords 去掉本该删除的词
	FilterDeleteErrorWords(ctx context.Context, ids []int64, rumTableName string) []int64
}

type RumCacheImpl struct {
	redisClient redis.Client
	rumClient   rpc.RumClient[float32]
}

func NewRumCache() RumCache {
	return &RumCacheImpl{
		redisClient: redis.NewClient("rum_cache"),
		rumClient:   impl.DefaultFloat32RumClientImpl,
	}
}

func (r *RumCacheImpl) getRedisKey(rumTableName string) string {
	return fmt.Sprintf("rum_cache:delete_error:%s", rumTableName)
}

func (r *RumCacheImpl) SaveDeleteErrorCache(ctx context.Context, id int64, rumTableName string) {
	logger := log.WithFields(ctx, map[string]any{
		"class": "RumCache",
		"func":  "SaveDeleteErrorCache",
	})
	redisKey := r.getRedisKey(rumTableName)
	_, err := r.redisClient.SAdd(ctx, redisKey, id).Result()
	if err != nil {
		logger.Errorf(ctx, "id:%d is saved to delete error cache, error => %v", id, err)
	}
}

func (r *RumCacheImpl) RemoveDeleteErrorCache(ctx context.Context, id int64, rumTableName string) {
	logger := log.WithFields(ctx, map[string]any{
		"class": "RumCache",
		"func":  "RemoveDeleteErrorCache",
	})
	redisKey := r.getRedisKey(rumTableName)
	_, err := r.redisClient.SRem(ctx, redisKey, id).Result()
	if err != nil {
		logger.Errorf(ctx, "id:%d is removed from delete error cache, error => %v", id, err)
	}
}

func (r *RumCacheImpl) FilterDeleteErrorWords(ctx context.Context, ids []int64, rumTableName string) []int64 {
	var result []int64
	logger := log.WithFields(ctx, map[string]any{
		"class": "RumCache",
		"func":  "IsExistDeleteErrorCache",
	})
	deleteErrorWordIds := r.getDeleteErrorWordIds(ctx, rumTableName)
	var deleteIds []int64
	for _, id := range ids {
		if !lo.Contains(deleteErrorWordIds, id) {
			result = append(result, id)
		} else {
			deleteIds = append(deleteIds, id)
			logger.Infof(ctx, "delete word id :%d", id)
		}
	}

	// 如果判断内容 存在与删除缓存中 则开启协程 额外再删一次
	safe_group.SafeGo(func() error {
		newCtx, cancel := context.WithTimeout(util.WithoutCancel(ctx), 1*time.Second)
		defer cancel()
		// 删除 rum
		for _, deleteId := range deleteIds {
			_ = r.rumClient.RumDelete(newCtx, rumTableName, deleteId, "")
		}
		return nil
	}, "Delete Rum Data")
	return result
}

func (r *RumCacheImpl) getDeleteErrorWordIds(ctx context.Context, rumTableName string) []int64 {
	res := make(map[string][]int64, 1)
	redisKey := r.getRedisKey(rumTableName)

	resource.RedisLocalCache.BatchGet(ctx, []string{redisKey}, util.StringKeyGeneratorFunc,
		func(redisKeys interface{}) interface{} {
			oneRedisKey := redisKeys.([]string)[0]
			resultMap := make(map[string][]int64, 1)
			res, sErr := r.redisClient.SMembers(ctx, oneRedisKey).Result()
			if sErr != nil {
				log.Infof(ctx, "get redis key:%s error => %v", oneRedisKey, sErr)
				return resultMap
			}
			resultMap[oneRedisKey] = lo.Map(res, func(item string, _ int) int64 {
				return cast.ToInt64(item)
			})
			return resultMap
		}, &res, util.RemovedWordsKeyOption)
	return res[redisKey]
}
