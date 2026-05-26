package recall

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	basicConf "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/entities_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/recall/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type RumRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	rumClient rpc.RumClient[float32]
	rumTables []string
	kbSource  conf.KbSource
}

func NewRumRecallLogic(name string, config map[string]string) *RumRecallLogic {
	res := &RumRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.rumClient = impl.NewRumClientImpl[float32](basicConf.GetRumConfig(), 2000)
	res.kbSource = conf.KbSource(config[conf.SummaryRecallSource.ToConvert()])
	res.rumTables = strings.Split(config[conf.RumTableName], ",")
	res.RecallFunc = res.recall

	return res
}

func (r *RumRecallLogic) recall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	startTime := time.Now().UnixMilli()
	resList := make([]*data_frame.ItemData[entities.Item], 0)
	resMap := map[string][]*data_frame.ItemData[entities.Item]{}

	logicContext := logic_context.InitLogicContextV2BySource[[]*entities.Item](ctx, requestCtx, r.GetName(), logic_context.CacheSourceByTidb, "recall.RumLogic.recall")
	ctx = logicContext.Ctx
	logCtx := logicContext.LogCtx
	defer func() {
		logicContext.DeferFunc(entities_util.DataFrameList2ItemList(&resList))
	}()
	// 如果有缓存 直接返回，直接返回
	if logicContext.CacheResp.IsOk && logicContext.CacheResp.Resp != nil && len(logicContext.CacheResp.Resp) > 0 {
		// data_frame 有些内部参数无法序列化，所以需要重新创建一下 item
		entities_util.ItemList2DataFrameListAndPush(&logicContext.CacheResp.Resp, requestCtx, &resList)
		return resList, nil
	}

	universalKnowledgeBaseType := requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.KnowledgeBaseType)
	topK := cast.ToInt32(requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.ConfigRecallSize))

	// 检查必要条件
	if requestCtx.GetBizContext().GetQueryMerge() == nil || requestCtx.GetBizContext().GetQueryMerge().ItemMeta == nil {
		r.logging(ctx, logCtx, requestCtx, r.rumTables, []float32{}, topK, []string{}, startTime, resMap)
		return resList, nil
	}

	queryConditions, embedding := util2.GetRumQueryConditions(r.GetName(), requestCtx)

	// 检查必要条件
	if len(embedding) == 0 || len(r.rumTables) == 0 || topK == 0 {
		r.logging(ctx, logCtx, requestCtx, r.rumTables, embedding, topK, queryConditions, startTime, resMap)
		return resList, nil
	}

	rumResultChan := make(chan [][]*rpc.SearchResult, len(r.rumTables)*len(queryConditions))
	group := safe_group.NewGroupWithTimeout("RumRecallLogic", 3000).SetLimit(4)

	for _, rumTable := range r.rumTables {
		for _, queryCondition := range queryConditions {
			group.Go(func() error {
				rumResult := r.rumClient.RumSearch(ctx, rumTable, [][]float32{embedding}, topK, queryCondition, util2.GetStoreFields(r.GetName()))
				select {
				case rumResultChan <- rumResult:
					// 成功发送
				case <-ctx.Done():
					return ctx.Err()
				}
				return nil
			})
		}
	}

	// 等待所有 goroutine 完成后再关闭 channel
	go func() {
		if err := group.Wait(); err != nil {
			log.Warnf(ctx, "RumRecallLogic group Wait Err => %v", err)
		}
		close(rumResultChan)
	}()

	var rumResultList [][]*rpc.SearchResult
	for res := range rumResultChan {
		rumResultList = append(rumResultList, res...)
	}

	for _, itemList := range rumResultList {
		for idx, searchItem := range itemList {
			item, err := util2.GenRumItem(ctx, r.GetName(), searchItem)
			if err != nil {
				log.Warnf(ctx, "genRumItem failed. error: %s", err.Error())
				continue
			}
			item.GetItemMeta().GetRecallSourceInfo().RecallRank = idx + 1
			item.GetItemMeta().GetRecallSourceInfo().KbSources = []conf.KbSource{r.kbSource}
			// 如果有明确指定的知识库类型，则使用指定的知识库类型
			if universalKnowledgeBaseType != "" {
				item.GetItemMeta().GetRecallSourceInfo().UniversalKnowledgeBaseType = enums.ParseKnowledgeBaseType(universalKnowledgeBaseType)
			}
			resList = append(resList, item.IntoFrameItem(requestCtx))
		}
	}

	log.StatsdRecall(ctx, r.kbSource.String(), "recall_content", len(resList))
	// 新
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".recall.%s.length", float64(len(resList)), r.kbSource.String())
	// 老
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".recall.%s.length", requestCtx.GetBizContext().Scenes(), r.kbSource.String()), float64(len(resList)))
	log.StatsdRecall(ctx, r.kbSource.String(), "recall_resp", len(resList))

	r.logging(ctx, logCtx, requestCtx, r.rumTables, embedding, topK, queryConditions, startTime, resMap)

	return resList, nil
}

func (r *RumRecallLogic) logging(ctx context.Context, logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	tables []string, embeddings []float32, topk int32, query []string, startTime int64, resMap map[string][]*data_frame.ItemData[entities.Item]) {
	for table, itemList := range resMap {
		util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".recall.%s.%s.length", float64(len(itemList)), "rum", table)
	}

	r.saveTracing(logCtx, requestCtx, tables, embeddings, topk, query, startTime, resMap)
}

func (r *RumRecallLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	tables []string, embeddings []float32, topk int32, query []string, startTime int64, resMap map[string][]*data_frame.ItemData[entities.Item]) {
	recallResult := map[string][]string{}
	for table, itemList := range resMap {
		recallResult[table] = lo.Map(itemList, func(item *data_frame.ItemData[entities.Item], index int) string {
			return item.GetBizItem().ToDescription()
		})
	}

	logicTracing := &proto.LogicTracing{
		LogicName:   r.GetName(),
		LogicInput:  []string{fmt.Sprintf("tables:%s, emb dim:%d, top:%d, query:%s", util.GetJSONIgnoreError(tables), len(embeddings), topk, util.GetJSONIgnoreError(query))},
		LogicOutput: []string{fmt.Sprintf("result:%s", util.GetJSONIgnoreError(recallResult))},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(r.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, fmt.Sprintf("tables:%s, emb dim:%d, top:%d, query:%s", util.GetJSONIgnoreError(tables), len(embeddings), topk, util.GetJSONIgnoreError(query)))
	constant.DataOutputNodeLog.Infof(logCtx, fmt.Sprintf("result:%s", util.GetJSONIgnoreError(recallResult)))

}
