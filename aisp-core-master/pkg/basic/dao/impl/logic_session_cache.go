package impl

import (
	"context"
	"encoding/json"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

var redisClient = resource.SessionCache

type LogicSessionCacheImpl[T any] struct {
}

func NewLogicSessionCacheDao[T any]() dao.LogicSessionCacheDao[T] {
	return &LogicSessionCacheImpl[T]{}
}

func (l *LogicSessionCacheImpl[T]) getLogicSessionCacheRedisKey(scene string, logicName string, sessionId int64) string {
	return fmt.Sprintf("logic_session_cache:scene:%s:logic_name:%s:session_id:%d", scene, logicName, sessionId)
}

func (l *LogicSessionCacheImpl[T]) SaveCache(ctx context.Context, scene string, logicName string, sessionId int64, items *T) error {
	// 生成对redis hash 操作的代码， 可以使用 l.redisClient 进行操作，需要设置ttl
	//	要求 是 redis key 为 scene + sessionId， field 为 logicName， value 为 items
	//	items 为一个数组，每个元素为一个 Item 对象，存入redis 时需要序列化
	//	请注意序列化的方式，可以使用 pb.Marshal 进行序列化
	//	请注意序列化后的数据类型，可以使用 string() 进行转换

	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "LogicSessionCacheDao.SaveCache",
		"scene":     scene,
		"logicName": logicName,
		"sessionId": sessionId,
	})

	// 序列化
	jsonData, err := json.Marshal(dao.CacheData[T]{Data: items})
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "json marshal error.")
		return err
	}

	redisKey := l.getLogicSessionCacheRedisKey(scene, logicName, sessionId)
	result, err := redisClient.SetEX(ctx, redisKey, jsonData, dao.SessionCacheTTL).Result()
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "redis set error. result=%s, key=%s", result, redisKey)
	}
	return err
}

func (l *LogicSessionCacheImpl[T]) RemoveCache(ctx context.Context, scene string, logicName string, sessionId int64) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "LogicSessionCacheDao.RemoveCache",
		"scene":     scene,
		"logicName": logicName,
		"sessionId": sessionId,
	})

	redisKey := l.getLogicSessionCacheRedisKey(scene, logicName, sessionId)
	result, err := redisClient.Del(ctx, redisKey).Result()
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "redis del error. result=%d, key=%s", result, redisKey)
	}
	return err
}

func (l *LogicSessionCacheImpl[T]) GetCache(ctx context.Context, scene string, logicName string, sessionId int64) (*T, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "LogicSessionCacheDao.GetCache",
		"scene":     scene,
		"logicName": logicName,
		"sessionId": sessionId,
	})

	redisKey := l.getLogicSessionCacheRedisKey(scene, logicName, sessionId)
	result, err := redisClient.Get(ctx, redisKey).Result()
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "redis get error. result=%s, key=%s", result, redisKey)
		return nil, err
	}

	// 反序列化
	var deserializedItems dao.CacheData[T]
	err = json.Unmarshal([]byte(result), &deserializedItems)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "error deserializing JSON: %s", result)
		return nil, err
	}
	return deserializedItems.Data, nil
}
