package retrieval

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// RetrievalMergeLogic 多路召回merge
// @logicAuthor: quanrui
type RetrievalMergeLogic struct {
	*logic.BaseLogic[entities.RequestContext]
}

func NewRetrievalMergeLogic(name string, config map[string]string) *RetrievalMergeLogic {
	res := &RetrievalMergeLogic{
		BaseLogic: logic.NewBaseLogic[entities.RequestContext](name, config),
	}
	res.RealDoFunc = res.merge
	return res
}

func (r *RetrievalMergeLogic) merge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {
	logger := log.WithFields(ctx, map[string]any{
		"func": "RetrievalMergeLogic.merge",
	})

	allRetrieveItems := make([]*rpc.OutSiteSearchRecallAnswerResult, 0)

	for i := 0; i < r.GetInputSize(); i++ {
		kbSource := r.GetInputName(i)
		retrieveItems := r.getRetrieveItems(ctx, requestCtx, r.GetInputName(i))
		if len(retrieveItems) == 0 {
			logger.Warnf(ctx, "no retrieve items for kbSource: %s", kbSource)
			continue
		}

		allRetrieveItems = append(allRetrieveItems, retrieveItems...)
	}

	logger.Infof(ctx, "allRetrieveItems: %v", allRetrieveItems)

	requestCtx.DataMap().SetObjMap(ctx, r.GetOutputName(0), allRetrieveItems)
	return nil
}

func (r *RetrievalMergeLogic) getRetrieveItems(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], dataKey string) []*rpc.OutSiteSearchRecallAnswerResult {
	retrieveItems, ok := requestCtx.DataMap().GetObjMap(ctx, dataKey)
	if !ok {
		return nil
	}

	return retrieveItems.([]*rpc.OutSiteSearchRecallAnswerResult)
}
