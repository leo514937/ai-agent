package impl

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
)

type HotEventIndexDaoImpl struct {
	redisClient redis.Client
}

var _ dao.HotEventIndexDao = (*HotEventIndexDaoImpl)(nil)

var DefaultHotEventIndexDaoImpl *HotEventIndexDaoImpl

const eventTtl = 15 * 24 * time.Hour

func init() {
	DefaultHotEventIndexDaoImpl = NewHotEventIndexDaoImpl()
}

func NewHotEventIndexDaoImpl() *HotEventIndexDaoImpl {
	return &HotEventIndexDaoImpl{
		redisClient: resource.DashboardAsyncRequest,
	}
}

func (d *HotEventIndexDaoImpl) getWordTimelinessRedisKey(wordId int64) string {
	return fmt.Sprintf("aisp-core:hot_envent:word_timeliness:%d", wordId)
}

func (d *HotEventIndexDaoImpl) getWordOriginId2IdRedisKey(wordOriginId int64) string {
	return fmt.Sprintf("aisp-core:hot_envent:origin_id:%d", wordOriginId)
}

func (d *HotEventIndexDaoImpl) SetWordCreateTimeAndTimeliness(ctx context.Context, wordId int64, timeliness macro.TimelinessType) error {
	redisKey := d.getWordTimelinessRedisKey(wordId)
	responseStr := fmt.Sprintf("%s:%d", timeliness, time.Now().Unix())
	result, err := d.redisClient.SetEX(ctx, redisKey, responseStr, eventTtl).Result()
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "redis set error. result=%s, key=%s", result, redisKey)
	}
	return err
}

func (d *HotEventIndexDaoImpl) GetWordCreateTimeAndTimeliness(ctx context.Context, wordId int64) (int64, macro.TimelinessType) {
	redisKey := d.getWordTimelinessRedisKey(wordId)
	res, err := d.redisClient.Get(ctx, redisKey).Result()
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "redis get error. key:%s", redisKey)
		return 0, ""
	}
	resSlice := strings.Split(res, ":")
	if len(resSlice) != 2 {
		return 0, ""
	}

	createTime, castErr := util.String2Int64(resSlice[1])
	if castErr != nil {
		log.WithError(ctx, castErr).Errorf(ctx, "cast int64 err. origin:%s", res)
		return 0, ""
	}

	return createTime, macro.TimelinessType(resSlice[0])
}

func (d *HotEventIndexDaoImpl) SetWordOriginId2WordId(ctx context.Context, wordOriginId int64, wordId int64) error {
	redisKey := d.getWordOriginId2IdRedisKey(wordOriginId)
	result, err := d.redisClient.SetEX(ctx, redisKey, wordId, eventTtl).Result()
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "redis set error. result=%s, key=%s", result, redisKey)
	}
	return err
}

func (d *HotEventIndexDaoImpl) GetWordOriginId2WordId(ctx context.Context, wordOriginId int64) int64 {
	redisKey := d.getWordOriginId2IdRedisKey(wordOriginId)
	res, err := d.redisClient.Get(ctx, redisKey).Int64()
	if err != nil {
		return 0
	}

	return res
}
