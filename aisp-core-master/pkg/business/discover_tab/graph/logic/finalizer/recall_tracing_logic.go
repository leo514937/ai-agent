package finalizer

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/finalizer"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph/model"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// RecallTracingRecordLogic 召回服务记录 tracing 日志
// @logicAuthor: wangran
type RecallTracingRecordLogic struct {
	*finalizer.TracingRecordLogic
}

func NewRecallTracingRecordLogic(name string, config map[string]string) *RecallTracingRecordLogic {
	res := &RecallTracingRecordLogic{
		TracingRecordLogic: finalizer.NewTracingRecordLogic(name, config),
	}
	res.GenRequestInfoFunc = res.genRequestInfoFunc
	res.GenResponseInfoFunc = res.genResponseInfoFunc
	return res
}

func (t *RecallTracingRecordLogic) genRequestInfoFunc(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	request := requestCtx.GetBizContext().ProductContext().(*model.RecallContext).RequestInfo()
	return util.GetJSONIgnoreError(request)
}

func (t *RecallTracingRecordLogic) genResponseInfoFunc(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	resp := requestCtx.GetBizContext().ResponseItemList()
	respRecallItems := make([]*proto.ZhidaRecallItem, 0, len(resp))

	for _, item := range resp {
		respRecallItems = append(respRecallItems, item.ToRecallItem())
	}

	return util.GetJSONIgnoreError(&proto.ZhidaRecallResponse{
		RecallItems: respRecallItems,
	})
}
