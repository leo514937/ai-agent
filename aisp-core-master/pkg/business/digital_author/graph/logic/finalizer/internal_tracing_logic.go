package finalizer

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	digitalModel "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/finalizer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type InternalTracingRecordLogic struct {
	*finalizer.TracingRecordLogic
}

func NewInternalTracingRecordLogic(name string, config map[string]string) *InternalTracingRecordLogic {
	res := &InternalTracingRecordLogic{
		TracingRecordLogic: finalizer.NewTracingRecordLogic(name, config),
	}
	res.GenRequestInfoFunc = genRequestInfoFunc
	res.GenResponseInfoFunc = genResponseInfoFunc
	return res
}

func genRequestInfoFunc(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	request := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).RequestInfo()
	return util.GetJSONIgnoreError(request)
}

func genResponseInfoFunc(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {

	// 返回的 itemList
	resItems := requestCtx.GetBizContext().ResponseItemList()

	// 为空的直接返回""
	if len(resItems) == 0 {
		return ""
	}

	resItem := resItems[0]
	digitalAuthorContext := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext)
	hitTask := digitalAuthorContext.HitTask()
	multiChatSummary := digitalAuthorContext.MultiChatSummary()

	response := &proto.ChatResponse{
		State:    proto.ChatState_COMPLETED,
		Message:  resItem.ToChatMessage(),
		RespType: resItem.ChatRespType,
	}

	if hitTask.GetId() != 0 {
		response.ExtraRespInfo = &proto.ExtraRespInfo{
			TaskId:  hitTask.GetId(),
			Summary: multiChatSummary,
		}
	}

	return util.GetJSONIgnoreError(response)
}
