package impl

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
)

type DigitalAuthorIndexDaoImpl struct {
	redisClient redis.Client
}

var _ dao.DigitalAuthorIndexDao = (*DigitalAuthorIndexDaoImpl)(nil)

var DefaultFeatureUsageInfoDaoImpl *DigitalAuthorIndexDaoImpl

const ttl = 90 * 24 * time.Hour

func init() {
	DefaultFeatureUsageInfoDaoImpl = NewFeatureUsageInfoDaoImpl()
}

func NewFeatureUsageInfoDaoImpl() *DigitalAuthorIndexDaoImpl {
	return &DigitalAuthorIndexDaoImpl{
		redisClient: resource.DashboardAsyncRequest,
	}
}

func (d *DigitalAuthorIndexDaoImpl) getOnSiteIndexStatusRedisKey(docId int64, docType content.DocType_Type) string {
	return fmt.Sprintf("digital-author:onsite_index_status:%d:%d", docType, docId)
}

func (d *DigitalAuthorIndexDaoImpl) SetOnSiteIndexStatus(ctx context.Context, docId int64, docType content.DocType_Type, status bool) error {
	redisKey := d.getOnSiteIndexStatusRedisKey(docId, docType)
	_, err := d.redisClient.SetEX(ctx, redisKey, status, ttl).Result()
	return err
}

func (d *DigitalAuthorIndexDaoImpl) GetOnSiteIndexStatus(ctx context.Context, docId int64, docType content.DocType_Type) (bool, error) {
	redisKey := d.getOnSiteIndexStatusRedisKey(docId, docType)
	res, err := d.redisClient.Get(ctx, redisKey).Bool()
	// 对于有使用的 item，重置其过期时间
	if err == nil {
		d.redisClient.Expire(ctx, redisKey, ttl)
	}
	return res, err
}
