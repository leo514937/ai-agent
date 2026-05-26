package impl

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"runtime"
	"time"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
)

var dbOrm = mysql.AispCoreBorm

type LogicSessionCacheByTiDBImpl[T any] struct {
}

func NewLogicSessionCacheByTiDBImpl[T any]() dao.LogicSessionCacheDao[T] {
	return &LogicSessionCacheByTiDBImpl[T]{}
}

func NewLogicSessionCacheByTiDBImplBySource[T any]() *LogicSessionCacheByTiDBImpl[T] {
	return &LogicSessionCacheByTiDBImpl[T]{}
}

func (l *LogicSessionCacheByTiDBImpl[T]) getLogicSessionCacheRedisKey(scene string, logicName string, sessionId int64) string {
	return fmt.Sprintf("logic_session_cache:scene:%s:logic_name:%s:session_id:%d", scene, logicName, sessionId)
}

func (l *LogicSessionCacheByTiDBImpl[T]) SaveCache(ctx context.Context, scene string, logicName string, sessionId int64, items *T) error {
	// 生成对redis hash 操作的代码， 可以使用 l.redisClient 进行操作，需要设置ttl
	//	要求 是 redis key 为 scene + sessionId， field 为 logicName， value 为 items
	//	items 为一个数组，每个元素为一个 Item 对象，存入redis 时需要序列化
	//	请注意序列化的方式，可以使用 pb.Marshal 进行序列化
	//	请注意序列化后的数据类型，可以使用 string() 进行转换
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "LogicSessionCacheByTiDB.SaveCache",
		"scene":     scene,
		"logicName": logicName,
		"sessionId": sessionId,
	})

	// 捕获 panic 输出日志
	defer func() {
		if panic_ := recover(); panic_ != nil {
			// 判断是否是 runtime.Error 类型
			if err, ok := panic_.(runtime.Error); ok {
				// 判断错误信息是否包含空指针相关内容
				if err.Error() == "runtime error: invalid memory address or nil pointer dereference" {
					logger.WithField(ctx, "panic", "invalid memory address or nil pointer dereference").Errorf(ctx, "panic in save cache")
				} else {
					logger.WithField(ctx, "panic", err.Error()).Errorf(ctx, "panic in save cache")
				}
			} else {
				logger.WithField(ctx, "panic", panic_).Errorf(ctx, "panic in save cache")
			}
		}
	}()

	// 序列化
	jsonData, err := json.Marshal(dao.CacheData[T]{Data: items})
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "json marshal error.")
		return err
	}

	cacheKey := l.getLogicSessionCacheRedisKey(scene, logicName, sessionId)

	// 获取当前时间
	now := time.Now()
	// 判断是否存在
	cacheObject := &model.LogicSessionCache{}
	// 判断是否存在
	ormErr := dbOrm.Where(borm.Eq{"cache_key": cacheKey}).One(ctx, cacheObject)
	if ormErr == nil || errors.Is(ormErr, borm.ErrRecordNotFound) {
		cacheObject.CacheKey = cacheKey
		cacheObject.CacheValue = string(jsonData)
		cacheObject.ExpireTime = now.Add(dao.SessionCacheTTL)
		if errors.Is(ormErr, borm.ErrRecordNotFound) {
			insertResult := dbOrm.Create(ctx, cacheObject)
			if insertResult.Error != nil {
				return insertResult.Error
			}
		} else {
			updateQueryResult := dbOrm.Save(ctx, cacheObject)
			if updateQueryResult.Error != nil {
				return updateQueryResult.Error
			}
		}
	} else {
		logger.WithError(ctx, err).Errorf(ctx, "tidb get Cache error. cacheKey:%s", cacheKey)
		return ormErr
	}
	return nil
}

func (l *LogicSessionCacheByTiDBImpl[T]) RemoveCache(ctx context.Context, scene string, logicName string, sessionId int64) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "LogicSessionCacheByTiDB.RemoveCache",
		"scene":     scene,
		"logicName": logicName,
		"sessionId": sessionId,
	})

	cacheKey := l.getLogicSessionCacheRedisKey(scene, logicName, sessionId)
	delError := dbOrm.Delete(ctx, borm.Eq{"cache_key": cacheKey})
	if delError != nil {
		logger.WithError(ctx, delError).Errorf(ctx, "tidb del error. key=%s", cacheKey)
	}
	return delError
}

func (l *LogicSessionCacheByTiDBImpl[T]) GetCache(ctx context.Context, scene string, logicName string, sessionId int64) (*T, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":      "LogicSessionCacheByTiDB.GetCache",
		"scene":     scene,
		"logicName": logicName,
		"sessionId": sessionId,
	})

	cacheKey := l.getLogicSessionCacheRedisKey(scene, logicName, sessionId)
	// 判断是否存在
	cacheObject := &model.LogicSessionCache{}
	// 判断是否存在
	ormErr := dbOrm.Where(borm.Eq{"cache_key": cacheKey}).One(ctx, cacheObject)
	if ormErr != nil {
		logger.WithError(ctx, ormErr).Errorf(ctx, "tidb getCache error. key=%s", cacheKey)
		return nil, ormErr
	}

	// 比较缓存是否过期
	if time.Now().After(cacheObject.ExpireTime) {
		logger.Infof(ctx, "cache expired. key=%s", cacheKey)
		return nil, nil
	}

	// 反序列化
	var deserializedItems dao.CacheData[T]
	deserializedErr := json.Unmarshal([]byte(cacheObject.CacheValue), &deserializedItems)
	if deserializedErr != nil {
		logger.WithError(ctx, deserializedErr).Errorf(ctx, "error deserializing JSON: %s", cacheObject.CacheValue)
		return nil, deserializedErr
	}

	return deserializedItems.Data, nil
}

func (l *LogicSessionCacheByTiDBImpl[T]) ClearExpireCache(ctx context.Context) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "LogicSessionCacheByTiDB.ClearExpireCache",
	})

	logger.Infof(ctx, "do clear expire cache.")
	limit := 500
	cacheList := make([]*model.LogicSessionCache, 0)
	ormErr := dbOrm.Where(borm.LT{
		"created_at": time.Now().Add(3 * -30 * 24 * time.Hour).Format("2006-01-02 15:04:05"),
	}).OrderBy("created_at").Limit(limit+1).All(ctx, &cacheList)
	if ormErr != nil {
		logger.WithError(ctx, ormErr).Errorf(ctx, "tidb check data error.")
		return
	}

	if len(cacheList) > 0 {
		delError := dbOrm.Delete(ctx, cacheList[0:zrecUtil.Min(limit, len(cacheList))])
		if delError != nil {
			logger.WithError(ctx, delError).Errorf(ctx, "tidb clear expire Cache error. => %s", delError.Error())
			return
		}
		// 存在可删除内容 则继续删除
		if len(cacheList) > limit {
			// 休眠0.1秒
			time.Sleep(100 * time.Millisecond)
			l.ClearExpireCache(ctx)
		}
	}
}
