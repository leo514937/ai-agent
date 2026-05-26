package impl

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"github.com/cespare/xxhash/v2"
)

type ZhidaOutSiteIndexDaoImpl struct {
	redisClient redis.Client
}

var _ dao.ZhidaOutSiteIndexDao = (*ZhidaOutSiteIndexDaoImpl)(nil)

var DefaultZhidaOutSiteIndexDaoImpl *ZhidaOutSiteIndexDaoImpl

func init() {
	DefaultZhidaOutSiteIndexDaoImpl = NewZhidaOutSiteIndexDaoImpl()
}

func NewZhidaOutSiteIndexDaoImpl() *ZhidaOutSiteIndexDaoImpl {
	return &ZhidaOutSiteIndexDaoImpl{
		redisClient: resource.DashboardAsyncRequest,
	}
}

func (d *ZhidaOutSiteIndexDaoImpl) getUpdateLockRedisKey(url string, content string) string {
	uniqueId := int64(xxhash.Sum64String(fmt.Sprintf("%s-%s", url, content)))
	return fmt.Sprintf("aisp-core:zhida_index_update:%d", uniqueId)
}

// 同一个 url+正文hash 3天之内不重复更新
func (d *ZhidaOutSiteIndexDaoImpl) GetItemUpdateLock(ctx context.Context, url string, content string) bool {
	redisKey := d.getUpdateLockRedisKey(url, content)
	succ, err := d.redisClient.SetNX(ctx, redisKey, "1", 3*24*time.Hour).Result()
	if err != nil {
		log.Errorf(ctx, "GetItemUpdateLock err:%v", err)
	}
	return succ
}
