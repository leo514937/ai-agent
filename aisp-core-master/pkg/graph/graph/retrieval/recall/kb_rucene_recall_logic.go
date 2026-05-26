package recall

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/knowledge_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/entities_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/recall/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/spf13/cast"
)

type RuceneLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	ruceneRpc rpc.RuceneServiceRPC
	path      string
	index     string
	kbSource  conf.KbSource
}

func NewRuceneLogic(name string, config map[string]string) *RuceneLogic {
	res := &RuceneLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.ruceneRpc = rpc.DefaultRuceneServiceRPC
	res.path = config[conf.RucenePath]
	res.index = config[conf.RuceneIndex]
	res.kbSource = conf.KbSource(config[conf.SummaryRecallSource.ToConvert()])
	res.RecallFunc = res.recall

	return res
}

func (r *RuceneLogic) recall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	startTime := time.Now().UnixMilli()
	resList := make([]*data_frame.ItemData[entities.Item], 0)
	logicContext := logic_context.InitLogicContextV2BySource[[]*entities.Item](ctx, requestCtx, r.GetName(), logic_context.CacheSourceByTidb, "recall.RuceneLogic.recall")
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

	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	universalKnowledgeBaseType := requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.KnowledgeBaseType)
	recallSize := cast.ToInt(requestCtx.GetBizContext().GetLogicConfig(r.GetName(), conf.ConfigRecallSize))
	conditions := util2.GetRuceneQueryCondition(r.GetName(), requestCtx)

	// 检查必要条件
	if len(conditions) == 0 || r.path == "" || r.index == "" || recallSize == 0 {
		return resList, nil
	}

	ruceneResultChan := make(chan *client.Response, len(conditions))
	group := safe_group.NewGroupWithTimeout("RuceneRecallLogic", 3000).SetLimit(4)

	for _, condition := range conditions {
		group.Go(func() error {
			searchRequest := knowledge_base.BuildRuceneQueryRequest(ctx, condition, r.path, r.index, []string{"*"})
			queryRequest := &client.SearchQueryRequest{
				From:        0,
				Size:        recallSize,
				QueryDef:    searchRequest.QueryDef,
				StoreFields: searchRequest.QueryFields,
			}

			searchResp, err := r.ruceneRpc.Search(ctx, ruceneHost, searchRequest.RucenePath, searchRequest.Index, queryRequest)
			if err != nil {
				log.Errorf(ctx, "RuceneLogic.recall error:%v", err)
				select {
				case ruceneResultChan <- nil:
					// 成功发送
				case <-ctx.Done():
					return ctx.Err()
				}
				return err
			}
			select {
			case ruceneResultChan <- searchResp:
				// 成功发送
			case <-ctx.Done():
				return ctx.Err()
			}
			return nil
		})
	}

	// 等待所有 goroutine 完成后再关闭 channel
	go func() {
		if err := group.Wait(); err != nil {
			log.Warnf(ctx, "RuceneRecallLogic group Wait Err => %v", err)
		}
		close(ruceneResultChan)
	}()

	var ruceneResultList []*client.Response
	for res := range ruceneResultChan {
		ruceneResultList = append(ruceneResultList, res)
	}

	for _, ruceneResult := range ruceneResultList {
		if ruceneResult == nil {
			continue
		}
		for idx, hit := range ruceneResult.Hits {
			item := util2.GenRuceneItem(r.GetName(), &hit)
			if item == nil {
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

	r.saveTracing(logCtx, requestCtx, ruceneHost, r.path, r.index, conditions, startTime, resList)

	return resList, nil
}

func (r *RuceneLogic) saveTracing(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	host string, path string, index string, conditions []*model.MultiCondition, startTime int64, resList []*data_frame.ItemData[entities.Item]) {

	logicTracing := &proto.LogicTracing{
		LogicName:   r.GetName(),
		LogicInput:  []string{fmt.Sprintf("host:%s, path:%s, index:%s, request:%s", host, path, index, util.GetJSONIgnoreError(conditions))},
		LogicOutput: []string{fmt.Sprintf("result len:%d", len(resList))},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(r.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, fmt.Sprintf("host:%s, path:%s, index:%s, condition:%s", host, path, index, util.GetJSONIgnoreError(conditions)))
	constant.DataOutputNodeLog.Infof(logCtx, fmt.Sprintf("result len:%d", len(resList)))
}
