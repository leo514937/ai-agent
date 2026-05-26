package impl

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
)

type UserRequestDaoImpl struct {
	redisClient redis.Client
}

var _ dao.UserRequestDao = (*UserRequestDaoImpl)(nil)

var DefaultUserRequestDaoImpl *UserRequestDaoImpl

func init() {
	DefaultUserRequestDaoImpl = NewUserRequestDaoImpl()
}

func NewUserRequestDaoImpl() *UserRequestDaoImpl {
	return &UserRequestDaoImpl{
		redisClient: resource.DashboardAsyncRequest,
	}
}

func (d *UserRequestDaoImpl) getUpdateLockRedisKey(memberId int64, sceneType string) string {
	uniqueId := fmt.Sprintf("%d-%s", memberId, sceneType)
	return fmt.Sprintf("aisp-core:user_request:%s", uniqueId)
}

// 同一个用户、同一个场景，ttlSeconds 秒内不重复请求
func (d *UserRequestDaoImpl) GetUserRequestFrequencyLock(ctx context.Context, memberId int64, sceneType string, ttlSeconds int) bool {
	redisKey := d.getUpdateLockRedisKey(memberId, sceneType)
	succ, err := d.redisClient.SetNX(ctx, redisKey, "1", time.Duration(ttlSeconds)*time.Second).Result()
	if err != nil {
		log.Errorf(ctx, "GetUserRequestFrequencyLock err:%v", err)
	}
	return succ
}
