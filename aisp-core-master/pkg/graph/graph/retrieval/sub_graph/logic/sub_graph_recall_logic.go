package logic

import (
	"context"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	macro2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

type SubGraphRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	recallService *sub_graph.RecallService
}

func NewSubGraphRecallLogic(name string, config map[string]string) *SubGraphRecallLogic {
	res := &SubGraphRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.recallService = sub_graph.NewRecallService()
	res.RecallFunc = res.recall

	return res
}

func (r *SubGraphRecallLogic) recall(ctx context.Context, requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {

	itemListChan := make(chan []*data_frame.ItemData[entities.Item], len(requestContext.GetBizContext().GetQueryMergeList()))
	group := safe_group.NewGroupWithTimeout("SubGraphRecallLogic", 300*1000).SetLimit(4)
	startTime := time.Now().UnixMilli()

	// 对每一个 queryMerge 的结果，并发执行一次召回子图
	for _, queryMerge := range requestContext.GetBizContext().GetQueryMergeList() {
		group.Go(func() error {
			intentionStr, _ := requestContext.DataMap().GetString(ctx, macro2.ZagKeyIntention)
			request := &proto.ZhidaRecallRequest{
				MemberId: requestContext.GetBizContext().MemberId(),
				Query:    queryMerge.Text,
				RecallExtInfo: &proto.RecallExtInfo{
					ChatType:        proto.ChatType(proto.ChatType_value[requestContext.GetBizContext().GetBizType()]),
					ClientSource:    requestContext.GetBizContext().GetClientSource(),
					TrafficSource:   requestContext.GetBizContext().GetTrafficSource(),
					MessageId:       requestContext.GetBizContext().MessageId(),
					RequestId:       requestContext.GetCommonContext().RequestId(),
					ParentRequestId: requestContext.GetCommonContext().RequestId(),
					Intention:       intentionStr,
					KnowledgeBases:  requestContext.GetBizContext().GetKnowledgeBases(),
					ReferenceMount:  requestContext.GetBizContext().GetCurrReferenceMount().RefDatas,
				},
			}
			recallItems, err := r.recallService.Recall(ctx, request)

			if err != nil {
				log.WithError(ctx, err).Errorf(ctx, "SubGraphRecallLogic recall failed for query: %s", queryMerge.Text)
				return fmt.Errorf("recall failed for query %s: %w", queryMerge.Text, err)
			}

			items := lo.Map(recallItems, func(item *entities.Item, _ int) *data_frame.ItemData[entities.Item] {
				item.GetItemMeta().GetRecallSourceInfo().RecallQueryMerge = queryMerge.Text
				return item.IntoFrameItem(requestContext)
			})

			select {
			case itemListChan <- items:
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
			log.Warnf(ctx, "SubGraphRecallLogic group Wait Err => %v", err)
		}
		close(itemListChan)
	}()

	// 合并召回结果
	var itemList []*data_frame.ItemData[entities.Item]
	for items := range itemListChan {
		itemList = append(itemList, items...)
	}

	// 召回结果去重
	itemList = entities.ItemListMergeDuplicate(itemList)

	r.saveTracing(itemList, startTime, requestContext)

	return itemList, nil
}

func (r *SubGraphRecallLogic) saveTracing(itemList []*data_frame.ItemData[entities.Item], startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   r.GetName(),
		LogicOutput: []string{fmt.Sprintf("recall item count: %d", len(itemList))},
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(r.GetName(), logicTracing)
}
