package stream_chat

import (
	"context"
	"fmt"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// TracingHelper 追踪日志辅助类
type TracingHelper struct {
	logicName string
}

// NewTracingHelper 创建 TracingHelper 实例
func NewTracingHelper(logicName string) *TracingHelper {
	return &TracingHelper{
		logicName: logicName,
	}
}

// SaveSecurityTracing 保存安全审核追踪信息
func (t *TracingHelper) SaveSecurityTracing(security *model.Security, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	securityTracing := &proto.SecurityTracing{
		Stage:            proto.BusinessStage_GENERATION,
		RedLine:          security.RedLine,
		Faq:              security.FAQ,
		IsPass:           security.ReviewResult.GetIsAvailable(),
		FailReason:       security.ReviewResult.GetFailReason(),
		DoSecurityReview: security.ReviewResult != nil,
	}
	securityChan := requestCtx.GetBizContext().ProcessTracing().SecurityTracing
	if len(securityChan) < entities.MaxTracingChanSize {
		securityChan <- securityTracing
	}
}

// SaveTracing 保存逻辑追踪信息
func (t *TracingHelper) SaveTracing(logCtx context.Context, request *dto.ChatRequest, response string, startTime int64, firstTokenTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:    t.logicName,
		LogicInput:   []string{util.GetJSONIgnoreError(request)},
		LogicOutput:  []string{response},
		LogicProcess: fmt.Sprintf("first token time: %d ms", firstTokenTime-startTime),
		EdgeSelect:   "",
		StartTimeMs:  startTime,
		EndTimeMs:    time.Now().UnixMilli(),
		CostMs:       time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(t.logicName, logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(request))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", response)
}

// SaveTracingMiddleProcess 保存中间过程追踪信息
func (t *TracingHelper) SaveTracingMiddleProcess(request *dto.ChatRequest, response string, progressV *dto.ChatResponse, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	llmRecord := &proto.LlmRecord{
		ModelName: request.ModelName,
		Messages:  model.ChatRequestMessages2Messages(request.AIProfile, request.Messages),
		Param:     model.ChatRequest2LlmParam(request),
		Response:  response,
	}
	if progressV != nil {
		llmRecord.ResponseId = progressV.ResponseId
	}
	requestCtx.GetBizContext().GetMiddleProcess().Summary = llmRecord
}

// SaveAnswerTracing 保存回答追踪信息
func (t *TracingHelper) SaveAnswerTracing(answer string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], stage proto.BusinessStage) {
	answerRecord := &proto.LLMAnswer{
		Stage:  stage,
		Answer: answer,
	}

	answerChan := requestCtx.GetBizContext().ProcessTracing().LlmAnswer
	if len(answerChan) < entities.MaxTracingChanSize {
		answerChan <- answerRecord
	}
}
