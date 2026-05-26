package finalizer

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	discoverModel "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/chat_event"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/finalizer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// TracingRecordLogic 记录 tracing 日志
// @logicAuthor: wangran
// @logicInfo: 记录 tracing 日志 kafka->hive
// @logicInput: 0,1,2 | 在基类中
// @logicInput: 3 | 召回items合并截断后的结果 []*data_frame.ItemData[entities.Item]
// @logicInput: 4 | 相关词 []*proto.Query
type TracingRecordLogic struct {
	*finalizer.TracingRecordLogic
}

func NewTracingRecordLogic(name string, config map[string]string) *TracingRecordLogic {
	res := &TracingRecordLogic{
		TracingRecordLogic: finalizer.NewTracingRecordLogic(name, config),
	}
	res.GenRequestInfoFunc = res.genRequestInfoFunc
	res.GenResponseInfoFunc = res.genResponseInfoFunc
	return res
}

func (t *TracingRecordLogic) genRequestInfoFunc(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	request := requestCtx.GetBizContext().ProductContext().(*discoverModel.DiscoverTabContext).RequestInfo()
	return util.GetJSONIgnoreError(request)
}

func (t *TracingRecordLogic) genResponseInfoFunc(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	// 获取最后的resp
	lastResponse := requestCtx.GetBizContext().GetChatEventResponseHandler().TransitionSource(requestCtx.GetBizContext().GetChatEvent().GetAllEventData(), true, &chat_event.TransitionContext{
		IsHitCache: requestCtx.GetBizContext().IsHitCache(),
	})
	return util.GetJSONIgnoreError(lastResponse)
}
