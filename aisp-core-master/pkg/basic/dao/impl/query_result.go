package impl

import (
	"context"
	"encoding/base64"
	"fmt"
	"sort"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	pb "github.com/golang/protobuf/proto"
)

type QueryResultDaoImpl struct {
	redisClient redis.Client
}

var _ dao.QueryResultDao = (*QueryResultDaoImpl)(nil)

var DefaultQueryResultDaoImpl *QueryResultDaoImpl

// queryTTL 6 hours
const queryTTL = 6 * 60 * 60 * time.Second

func init() {
	DefaultQueryResultDaoImpl = NewQueryResultDaoImpl()
}

func NewQueryResultDaoImpl() *QueryResultDaoImpl {
	return &QueryResultDaoImpl{
		redisClient: resource.DashboardAsyncRequest,
	}
}

func (d *QueryResultDaoImpl) getQueryResultRedisKey(scene string, clientSource string, trafficSource string, chatModel string, ab map[string]string, query string) string {
	encodedKey := base64.StdEncoding.EncodeToString([]byte(query))

	// 将ab map按照字母序排序，kv-kv格式拼接
	var abStr string
	if len(ab) == 0 {
		abStr = "default"
	} else {
		var abPairs []string
		for k, v := range ab {
			abPairs = append(abPairs, fmt.Sprintf("%s%s", k, v))
		}
		sort.Strings(abPairs)
		abStr = strings.Join(abPairs, "-")
	}

	return fmt.Sprintf("query_result:scene:%s:%s:%s:%s:%s:query:%s", scene, clientSource, trafficSource, chatModel, abStr, encodedKey)
}

func (d *QueryResultDaoImpl) SetResponseInfoByTTL(ctx context.Context, scene string, clientSource string, trafficSource string, chatModel string, ab map[string]string, query string, responseInfo *proto.ChatResponse, ttl time.Duration) error {
	if ttl <= 0 {
		// 从apollo 中获取召回方案(EmbeddingBatchSize)
		defCacheTTL := config.GetInt(macro.ChatCacheDefTTLConfigName, 6*60*60)
		if defCacheTTL >= 0 {
			ttl = d.convertToDuration(defCacheTTL)
		} else {
			ttl = queryTTL
		}
	}

	response, marshalErr := pb.Marshal(responseInfo)
	if marshalErr != nil {
		return marshalErr
	}

	responseStr := string(response)
	redisKey := d.getQueryResultRedisKey(scene, clientSource, trafficSource, chatModel, ab, query)
	result, err := d.redisClient.SetEX(ctx, redisKey, responseStr, ttl).Result()
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "redis set error. result=%s, key=%s", result, redisKey)
	}
	return err
}

func (d *QueryResultDaoImpl) DeleteResponseInfo(ctx context.Context, scene string, clientSource string, trafficSource string, chatModel string, ab map[string]string, query string) error {
	redisKey := d.getQueryResultRedisKey(scene, clientSource, trafficSource, chatModel, ab, query)
	_, err := d.redisClient.Del(ctx, redisKey).Result()
	return err
}

func (d *QueryResultDaoImpl) GetResponseInfo(ctx context.Context, scene string, clientSource string, trafficSource string, chatModel string, ab map[string]string, query string) (*proto.ChatResponse, error) {
	redisKey := d.getQueryResultRedisKey(scene, clientSource, trafficSource, chatModel, ab, query)
	res, redisErr := d.redisClient.Get(ctx, redisKey).Result()
	if redisErr != nil {
		return nil, redisErr
	}

	if res == "" {
		return nil, nil
	}

	responseInfo := &proto.ChatResponse{}
	unmarshalErr := pb.Unmarshal([]byte(res), responseInfo)
	return responseInfo, unmarshalErr
}

func (d *QueryResultDaoImpl) convertToDuration(ttlBySecond int) time.Duration {
	// 创建时间类
	return time.Duration(ttlBySecond) * time.Second
}
