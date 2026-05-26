package impl

import (
	"context"
	"encoding/base64"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"github.com/spf13/cast"
)

type RelatedWordCacheDaoImpl struct {
	redisClient redis.Client
}

var _ dao.RelatedWordCacheDao = (*RelatedWordCacheDaoImpl)(nil)

const wordTTL = 24 * 30 * time.Hour

func NewRelatedWordCacheDao() dao.RelatedWordCacheDao {
	return &RelatedWordCacheDaoImpl{
		redisClient: resource.RedisByRelatedWord,
	}
}

func (d *RelatedWordCacheDaoImpl) getQueryResultRedisKey(scene string, key dao.RelatedWordCacheKey) string {
	return fmt.Sprintf("related_cache:scene:%s:%s", scene, key)
}

func (d *RelatedWordCacheDaoImpl) SaveCache(ctx context.Context, scene string, key dao.RelatedWordCacheKey, values []*entities.Item) error {
	responseStr, marshalErr := utils.MarshalToString(values)
	if marshalErr != nil {
		return marshalErr
	}
	redisKey := d.getQueryResultRedisKey(scene, key)
	result, err := d.redisClient.SetEX(ctx, redisKey, responseStr, wordTTL).Result()
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "redis set error. result=%s, key=%s", result, redisKey)
	}
	return err
}

func (d *RelatedWordCacheDaoImpl) GetCache(ctx context.Context, scene string, key dao.RelatedWordCacheKey) ([]*entities.Item, error) {
	redisKey := d.getQueryResultRedisKey(scene, key)
	res, redisErr := d.redisClient.Get(ctx, redisKey).Result()
	if redisErr != nil {
		return []*entities.Item{}, redisErr
	}

	if res == "" {
		return []*entities.Item{}, nil
	}
	resp := make([]*entities.Item, 0)
	unMarshalErr := utils.JSONUnmarshal([]byte(res), &resp)
	return resp, unMarshalErr
}

func (d *RelatedWordCacheDaoImpl) RemoveCache(ctx context.Context, scene string, key dao.RelatedWordCacheKey) error {
	redisKey := d.getQueryResultRedisKey(scene, key)
	_, err := d.redisClient.Del(ctx, redisKey).Result()
	return err
}

// ================== 以下为创建Key方法 ==================

func (d *RelatedWordCacheDaoImpl) CreateAskCacheKey(doc model.Content) dao.RelatedWordCacheKey {
	return dao.RelatedWordCacheKey(fmt.Sprintf("did:%s:dtype:%s", cast.ToString(doc.ContentID), cast.ToString(doc.GetDocType().String())))
}
func (d *RelatedWordCacheDaoImpl) CreateSearchAskCacheKey(memberId int64, query string) dao.RelatedWordCacheKey {
	encodeQuery := strings.ReplaceAll(strings.TrimSpace(query), " ", "&nbsp;")
	encodedKey := base64.StdEncoding.EncodeToString([]byte(encodeQuery))
	return dao.RelatedWordCacheKey(fmt.Sprintf("uid:%s:q:%s", cast.ToString(memberId), encodedKey))
}
