package impl

import (
	"context"
	"fmt"
	"strings"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"github.com/samber/lo"
)

type DocRelateQueryDaoImpl struct {
	redisClient redis.Client
}

var _ dao.DocRelateQueryDao = (*DocRelateQueryDaoImpl)(nil)

var DefaultDocRelateQueryDaoImpl *DocRelateQueryDaoImpl

func init() {
	DefaultDocRelateQueryDaoImpl = NewDocRelateQueryDaoImpl()
}

func NewDocRelateQueryDaoImpl() *DocRelateQueryDaoImpl {
	return &DocRelateQueryDaoImpl{
		redisClient: resource.DashboardAsyncRequest,
	}
}

func (d *DocRelateQueryDaoImpl) getDocRelateQueriesRedisKey(docId int64, docType content.DocType_Type) string {
	return fmt.Sprintf("aisp-core:doc_relate_query:%d:%d", docType, docId)
}

func (d *DocRelateQueryDaoImpl) getDocIndex2QueriesIndexRedisKey(docIndex int64) string {
	return fmt.Sprintf("aisp-core:doc_index2queries_index:%d", docIndex)
}

func (d *DocRelateQueryDaoImpl) SetDocRelateQueries(ctx context.Context, docId int64, docType content.DocType_Type, questions []string) bool {
	redisKey := d.getDocRelateQueriesRedisKey(docId, docType)

	questionStr := strings.Join(lo.Map(questions, func(s string, _ int) string {
		return strings.ReplaceAll(s, ",", "，")
	}), ",")

	_, err := d.redisClient.Set(ctx, redisKey, questionStr, 0).Result()
	if err != nil {
		return false
	}
	return true
}

func (d *DocRelateQueryDaoImpl) GetDocRelateQueries(ctx context.Context, docId int64, docType content.DocType_Type) []string {
	redisKey := d.getDocRelateQueriesRedisKey(docId, docType)
	questions, err := d.redisClient.Get(ctx, redisKey).Result()
	if err != nil {
		return nil
	}
	return strings.Split(questions, ",")
}

func (d *DocRelateQueryDaoImpl) SetDocIndex2QueriesIndex(ctx context.Context, docIndex int64, queriesIndex []int64) bool {
	redisKey := d.getDocIndex2QueriesIndexRedisKey(docIndex)
	queriesIndexStr := strings.Join(lo.Map(queriesIndex, func(i int64, _ int) string {
		return fmt.Sprintf("%d", i)
	}), ",")

	_, err := d.redisClient.Set(ctx, redisKey, queriesIndexStr, 0).Result()
	if err != nil {
		return false
	}
	return true
}

func (d *DocRelateQueryDaoImpl) GetDocIndex2QueriesIndex(ctx context.Context, docIndex int64) []int64 {
	redisKey := d.getDocIndex2QueriesIndexRedisKey(docIndex)
	queriesIndexStr, err := d.redisClient.Get(ctx, redisKey).Result()
	if err != nil {
		return nil
	}
	queriesIndexStrSlice := strings.Split(queriesIndexStr, ",")

	return lo.Map(queriesIndexStrSlice, func(s string, _ int) int64 {
		index, _ := util.String2Int64(s)
		return index
	})
}
