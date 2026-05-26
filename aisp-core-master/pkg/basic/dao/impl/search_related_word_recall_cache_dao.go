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
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"github.com/spf13/cast"
)

type SearchRelatedWordRecallCacheDaoImpl struct {
	redisClient redis.Client
}

var _ dao.SearchRelatedWordRecallCacheDao = (*SearchRelatedWordRecallCacheDaoImpl)(nil)

func NewSearchRelatedWordRecallCacheDao() dao.SearchRelatedWordRecallCacheDao {
	return &SearchRelatedWordRecallCacheDaoImpl{
		redisClient: resource.RedisByRelatedWordRecall,
	}
}

func (d *SearchRelatedWordRecallCacheDaoImpl) getQueryResultRedisKey(scene string, memberId int64, query string) string {
	encodedKey := base64.StdEncoding.EncodeToString([]byte(d.encodeQuery(query)))
	return fmt.Sprintf("related_recall_cache:scene:%s:uid:%s:q:%s", scene, cast.ToString(memberId), encodedKey)
}

func (d *SearchRelatedWordRecallCacheDaoImpl) SaveCache(ctx context.Context, scene string, memberId int64, query string, values []model.Content) error {
	responseStr, marshalErr := utils.MarshalToString(values)
	if marshalErr != nil {
		return marshalErr
	}
	redisKey := d.getQueryResultRedisKey(scene, memberId, query)
	result, err := d.redisClient.SetEX(ctx, redisKey, responseStr, 10*time.Minute).Result()
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "redis set error. result=%s, key=%s", result, redisKey)
	}
	return err
}

func (d *SearchRelatedWordRecallCacheDaoImpl) GetCache(ctx context.Context, scene string, memberId int64, query string) ([]model.Content, error) {
	redisKey := d.getQueryResultRedisKey(scene, memberId, query)
	res, redisErr := d.redisClient.Get(ctx, redisKey).Result()
	if redisErr != nil {
		return []model.Content{}, redisErr
	}
	resp := make([]model.Content, 0)
	if res == "" {
		return resp, nil
	}
	unMarshalErr := utils.JSONUnmarshal([]byte(res), &resp)
	return resp, unMarshalErr
}

func (d *SearchRelatedWordRecallCacheDaoImpl) RemoveCache(ctx context.Context, scene string, memberId int64, query string) error {
	redisKey := d.getQueryResultRedisKey(scene, memberId, query)
	_, err := d.redisClient.Del(ctx, redisKey).Result()
	return err
}

func (d *SearchRelatedWordRecallCacheDaoImpl) encodeQuery(word string) string {
	return strings.ReplaceAll(strings.TrimSpace(word), " ", "&nbsp;")
}
