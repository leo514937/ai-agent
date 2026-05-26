package operation_base

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/knowledge_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
	"git.in.zhihu.com/zrec/zrec-utils/redis/impl"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"git.in.zhihu.com/zrec/zrec-utils/task"
	"git.in.zhihu.com/zrec/zrec-utils/util"
)

var ruceneRpc rpc.RuceneServiceRPC
var statsPrefix = macro.OriginCommonStatsPrefix + ".%s.tracing.del_old_doc"

func init() {
	ctx := context.TODO()

	ruceneRpc = rpc.NewRuceneServiceRPC(8000 * time.Millisecond)
	redisClient := impl.NewBaseRedisImpl(redis.AispCoreRedis)
	periodSecond := int64(1 * util.DaySecond) // 执行周期：1day

	safe_group.SafeGo(func() error {
		for {
			// 使用 redis 做分布式锁，每次只有一个容器执行
			_ = task.SingleTask(ctx, redisClient, delRuceneOldDoc, "DelOldTracingRuceneDoc", periodSecond)
			// 使用 2 倍频率做检测，每半天检测一次锁有没有释放，最坏情况下 1.5d 执行一次该删除操作
			<-time.After(time.Duration(periodSecond/2) * time.Second)
		}
	}, "delOldTracingRuceneDoc panic")
}

func delRuceneOldDoc() error {
	ctx := context.TODO()

	log.Infof(ctx, "Crontab del old tracing data start.")
	ruceneQueryRequest := knowledge_base.BuildRuceneQueryRequest(ctx, getCondition(), model.Path, model.Index, macro.LogTracingStoreFields)

	// 现查一下，看看删除数据量，非必须
	queryRequest := &client.SearchQueryRequest{
		From:               0,
		Size:               1,
		QueryDef:           ruceneQueryRequest.QueryDef,
		StoreFields:        []string{},
		TransportTimeoutMs: 8000,
		EarlyTerminate:     100000000,
	}
	resp, err := ruceneRpc.Search(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), model.Path, model.Index, queryRequest)
	if err == nil && resp != nil {
		log.Infof(ctx, "del doc count:%d", resp.Total)
	}

	// 执行删除操作
	err = ruceneRpc.RemoveDocWithQuery(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), model.Path, model.Index, ruceneQueryRequest.QueryDef)

	if err != nil {
		statsd.Increment(fmt.Sprintf(statsPrefix, "crontab", "err"))
	} else {
		statsd.Increment(fmt.Sprintf(statsPrefix, "crontab", "success"))
	}

	return nil
}

// getCondition 构建删除旧 tracing 数据的查询条件
func getCondition() *model.MultiCondition {
	yearMilTimestamp := util.GetUnixTimestampToNow(0, 0, -365) * 1000
	monthMilTimestamp := util.GetUnixTimestampToNow(0, 0, -30) * 1000

	// zhida 主场景
	zhidaTrafficSourceConditions := []model.MultiCondition{
		{Condition: &model.Condition{
			FieldName:   macro.TracingFieldTrafficSource,
			FieldValue:  proto.TrafficSource_zhida.String(),
			OperateType: model.OperateTypeEq,
		}},
		{Condition: &model.Condition{
			FieldName:   macro.TracingFieldTrafficSource,
			FieldValue:  proto.TrafficSource_zhida_pro.String(),
			OperateType: model.OperateTypeEq,
		}},
	}

	// 30 天前的数据
	thirtyDayConditions := &model.Condition{
		FieldName:   macro.TracingFieldRequestTimeMs,
		FieldValue:  monthMilTimestamp,
		OperateType: model.OperateTypeLt,
	}

	// 1 年前的数据
	oneYearConditions := &model.Condition{
		FieldName:   macro.TracingFieldRequestTimeMs,
		FieldValue:  yearMilTimestamp,
		OperateType: model.OperateTypeLt,
	}

	// zhida 和 zhida_pro 的场景清除 1 年前的数据
	zhidaConditions := model.MultiCondition{
		Shoulds: zhidaTrafficSourceConditions,
		Musts:   []model.MultiCondition{{Condition: oneYearConditions}},
	}

	// 其余场景清除 1 个月前的数据
	otherTrafficSourceConditions := model.MultiCondition{
		MustNots: zhidaTrafficSourceConditions,
		Musts:    []model.MultiCondition{{Condition: thirtyDayConditions}},
	}

	return &model.MultiCondition{
		Shoulds: []model.MultiCondition{zhidaConditions, otherTrafficSourceConditions},
	}
}
