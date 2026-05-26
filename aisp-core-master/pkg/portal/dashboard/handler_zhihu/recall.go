package handler_zhihu

import (
	"git.in.zhihu.com/go/cafe/rest"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc"
)

// ZhidaRecallHandler 直答召回服务HTTP处理器
type ZhidaRecallHandler struct {
	rest.BaseHandler
	recallService *grpc.AispRecallService
}

// NewZhidaRecallHandler 创建直答召回服务处理器
func NewZhidaRecallHandler() rest.Handler {
	resources.Init(graph_constant.ApiRecall)
	return &ZhidaRecallHandler{
		recallService: grpc.NewAispRecallService(),
	}
}

// Post 处理POST请求，调用直答召回服务
func (h *ZhidaRecallHandler) Post(ctx *rest.Context) (rest.Response, error) {
	logger := log.WithField(ctx, "ZhidaRecallHandler.Post", "start")

	// 解析请求参数 - 修复：初始化request变量
	var request proto.ZhidaRecallRequest
	err := ctx.JSONArgs(&request)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to parse request")
		return nil, err
	}

	logger.Infof(ctx, "RequestParams:%v", request)

	// 调用召回服务
	response, err := h.recallService.GetZhidaRecall(ctx, &request)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "GetZhidaRecall failed")
		return nil, err
	}

	return ResponseSuccess(response)
}
