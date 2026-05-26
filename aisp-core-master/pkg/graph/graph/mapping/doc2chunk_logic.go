package mapping

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 归并映射算子，将 doc 映射成 chunk，从此 item 语义从 doc 变成 chunk

type Doc2ChunkLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewDoc2ChunkLogic(name string, config map[string]string) *Doc2ChunkLogic {
	res := &Doc2ChunkLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.realMapping
	return res
}

func (q *Doc2ChunkLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "mapping.Doc2ChunkLogic.realMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	startTime := time.Now().UnixMilli()
	result := make([]*data_frame.ItemData[entities.Item], 0)
	if items == nil || len(items) == 0 {
		return result, nil
	}

	// 此处进行归并和映射
	// each 模式 llm 策略：n 个 doc 映射成 n 个 summary
	// each 模式 rerank chunk top1 策略：n 个 doc 映射成 n 个 chunk
	// any 模式：n 个 doc 召回了 m 个 chunk，每个 chunk 都有 rerank 分数，配置决定选取方式。例如：
	//	1、每个 doc 选取 topk 的 chunk，总共 n*k 个
	//	2、所有 doc 选取 topk 的 chunk，总共 k 个

	q.saveTracing(items, result, startTime, requestCtx)
	return result, nil
}

func (q *Doc2ChunkLogic) saveTracing(inputItems []*data_frame.ItemData[entities.Item], outputItems []*data_frame.ItemData[entities.Item], startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName: q.GetName(),
		LogicInput: lo.Map(inputItems, func(item *data_frame.ItemData[entities.Item], _ int) string {
			return item.GetBizItem().ToDescription()
		}),
		LogicOutput: lo.Map(outputItems, func(item *data_frame.ItemData[entities.Item], _ int) string {
			return item.GetBizItem().ToDescription()
		}),
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(q.GetName(), logicTracing)
}
