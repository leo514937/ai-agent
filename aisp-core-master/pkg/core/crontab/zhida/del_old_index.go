package zhida

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/box/statsd"
	"git.in.zhihu.com/go/cafe/config"
	conf "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
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
var rumClient rpc.RumClient[float32]

var statsPrefix = macro.OriginCommonStatsPrefix + ".zhida_del_old.%s"

func init() {
	ctx := context.TODO()

	ruceneRpc = rpc.NewRuceneServiceRPC(5000 * time.Millisecond)
	rumClient = rpcImpl.NewRumClientImpl[float32](conf.GetRumConfig(), 5000)
	redisClient := impl.NewBaseRedisImpl(redis.AispCoreRedis)
	periodSecond := int64(1 * util.HourSecond) // 执行周期：1h

	safe_group.SafeGo(func() error {
		for {
			// 使用 redis 做分布式锁，每次只有一个容器执行
			_ = task.SingleTask(ctx, redisClient, DelOldDoc, "ZhidaDelOldIndexDoc", periodSecond)
			// 使用 2 倍频率做检测，每 0.5h 检测一次锁有没有释放，最坏情况下 1.5h 执行一次该删除操作
			<-time.After(time.Duration(periodSecond/2) * time.Second)
		}
	}, "delZhidaDelOldIndexDoc panic")
}

func DelOldDoc() error {
	ctx := context.TODO()
	log.Infof(ctx, "Crontab del zhida old index start.")

	ruceneQueryCondition := getOldDocRuceneQueryCondition()
	ruceneQueryRequest := knowledge_base.BuildRuceneQueryRequest(ctx, ruceneQueryCondition, model.ZhidaOutSitePath, model.ZhidaOutSiteIndex, []string{macro.ZhidaId})
	oldIds := searchOldDocId(ctx, ruceneQueryRequest)

	log.Infof(ctx, "prepare to remove %d docs.", len(oldIds))

	delRum(ctx, oldIds)
	err := delRucene(ctx, ruceneQueryRequest)

	log.Infof(ctx, "done remove %d docs.", len(oldIds))
	return err
}

func delRum(ctx context.Context, ids []int64) {
	for _, id := range ids {
		isSucc := rumClient.RumDelete(ctx, macro.ZhidaOutSiteRumTable, id, "")
		if !isSucc {
			log.Errorf(ctx, "zhida remove rum old data failed. id:%s")
		}
	}
}

func delRucene(ctx context.Context, ruceneQueryRequest *model.RuceneSearchRequest) error {
	err := ruceneRpc.RemoveDocWithQuery(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), model.ZhidaOutSitePath, model.ZhidaOutSiteIndex, ruceneQueryRequest.QueryDef)
	if err != nil {
		log.Errorf(ctx, "zhida remove rucene old data err. err:%v", err)
	}
	return err
}

func searchOldDocId(ctx context.Context, ruceneQueryRequest *model.RuceneSearchRequest) []int64 {
	queryRequest := &client.SearchQueryRequest{
		From:               0,
		Size:               10000,
		QueryDef:           ruceneQueryRequest.QueryDef,
		StoreFields:        []string{macro.ZhidaId},
		TransportTimeoutMs: 8000,
		EarlyTerminate:     1000000,
	}

	resp, err := ruceneRpc.Search(ctx, config.MustGetString(macro.BaiduRuceneProxyConfigName), model.ZhidaOutSitePath, model.ZhidaOutSiteIndex, queryRequest)
	if err != nil || resp == nil {
		if err != nil {
			statsd.Increment(fmt.Sprintf(statsPrefix, "crontab", "get_id_err"))
		}
		return []int64{}
	}

	var result []int64

	for _, item := range resp.Hits {
		docId := item.StoreFields.GetInt64(macro.ZhidaId)
		result = append(result, docId)
	}

	return result
}

func getOldDocRuceneQueryCondition() *model.MultiCondition {
	var publishTimeCondition *model.MultiCondition

	publishTimeCondition = &model.MultiCondition{
		Condition: &model.Condition{
			FieldName:   macro.ZhidaPublishTimeSecond,
			FieldValue:  util.GetUnixTimestampToNow(0, 0, -30),
			OperateType: model.OperateTypeLt,
		},
	}

	return publishTimeCondition
}
