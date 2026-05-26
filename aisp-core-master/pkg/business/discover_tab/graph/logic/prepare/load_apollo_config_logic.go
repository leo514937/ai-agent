package prepare

import (
	"context"
	"encoding/json"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/preparer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type recallOptionDto struct {
	enableCache                 bool
	recallEmbeddingBatchSize    int
	recallReRankBatchSize       int
	trafficSourceCacheSecTTlMap map[string]int
}

// @logicAuthor: zhoupengcheng
// @logicInfo: 加载apollo配置

type LoadApolloConfigLogic struct {
	*preparer.PreparerLogic[entities.RequestContext, entities.User, entities.Item, recallOptionDto]
	tagGrpcClient rpc.TagCoreGRPC
}

func NewLoadApolloConfigLogic(name string, config map[string]string) *LoadApolloConfigLogic {
	res := &LoadApolloConfigLogic{
		PreparerLogic: preparer.NewPreparerLogic[entities.RequestContext, entities.User, entities.Item, recallOptionDto](name, config),
	}

	res.FillUserFunc = res.getApolloConfig
	res.MergeUserFunc = res.setConfig
	res.tagGrpcClient = rpcImpl.NewTagCoreGrpcImpl()
	return res
}

func (r *LoadApolloConfigLogic) getApolloConfig(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) (recallOptionDto, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "root.RecallOptionLogic.getRecallOption")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))
	logger := log.WithFields(ctx, map[string]any{
		"func": "LoadApolloConfigLogic.getApolloConfig",
	})

	startTime := time.Now().UnixMilli()
	// enableCache 启用缓存开关
	enableCache := config.GetBool(macro.ChatEnableCacheConfigName, false)
	// 从apollo 中获取召回方案(EmbeddingBatchSize)
	recallEmbeddingBatchSize := config.GetInt(macro.ChatRecallEmbeddingBatchSizeConfigName, 1)
	// 从apollo 中获取召回方案(ReRankBatchSize)
	recallReRankBatchSize := config.GetInt(macro.ChatRecallReRankBatchSizeConfigName, 1)

	// 从apollo 中获取召回方案
	trafficSourceCacheSecTTlJson := config.GetString(macro.ChatCacheTTLByTrafficSourceConfigName, "")
	trafficSourceCacheSecTTlMap := make(map[string]int)
	err := json.Unmarshal([]byte(trafficSourceCacheSecTTlJson), &trafficSourceCacheSecTTlMap)
	if err != nil {
		logger.Errorf(ctx, "getRecallOption: unmarshal recallJson failed, err: %v", err)
	}

	result := recallOptionDto{
		enableCache:                 enableCache,
		recallEmbeddingBatchSize:    recallEmbeddingBatchSize,
		recallReRankBatchSize:       recallReRankBatchSize,
		trafficSourceCacheSecTTlMap: trafficSourceCacheSecTTlMap,
	}
	r.saveTracing(util.GetJSONIgnoreError(result), startTime, requestCtx)

	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(result))

	return result, nil
}

func (r *LoadApolloConfigLogic) setConfig(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], option recallOptionDto) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "root.RecallOptionLogic.setRecallOption")
	defer span.Finish()

	// 设置 summary 召回方案
	requestCtx.GetBizContext().SetEnableCache(option.enableCache)
	requestCtx.GetBizContext().SetSummaryRecallEmbeddingBatchSize(option.recallEmbeddingBatchSize)
	requestCtx.GetBizContext().SetSummaryRecallReRankBatchSize(option.recallReRankBatchSize)

	// 设置流量来源缓存ttl
	if option.trafficSourceCacheSecTTlMap != nil && len(option.trafficSourceCacheSecTTlMap) > 0 {
		for trafficSourceStr, secTTL := range option.trafficSourceCacheSecTTlMap {
			requestCtx.GetBizContext().PutChatCacheSecTTL(trafficSourceStr, secTTL)
		}
	}
	return nil
}

func (r *LoadApolloConfigLogic) saveTracing(recallOption string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   r.GetName(),
		LogicInput:  []string{},
		LogicOutput: []string{recallOption},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(r.GetName(), logicTracing)
}
