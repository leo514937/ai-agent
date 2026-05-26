package handler_zhihu

import (
	"git.in.zhihu.com/go/cafe/rest"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

// KnowledgeBaseDetailHandler 知识库详情服务HTTP处理器
type KnowledgeBaseDetailHandler struct {
	rest.BaseHandler
	aiIngressRPC rpc.AiIngressRPC
}

// NewKnowledgeBaseDetailHandler 创建知识库详情服务处理器
func NewKnowledgeBaseDetailHandler() rest.Handler {
	return &KnowledgeBaseDetailHandler{
		aiIngressRPC: impl.DefaultAiIngressRPCImpl,
	}
}

// 请求参数结构体
type KnowledgeBaseDetailRequest struct {
	MemberId         int64   `json:"member_id"`          // 用户ID
	KnowledgeBaseIds []int64 `json:"knowledge_base_ids"` // 知识库ID
	Limit            int64   `json:"limit"`              // 限制数量
}

// Post 处理POST请求，调用知识库详情服务
func (h *KnowledgeBaseDetailHandler) Post(ctx *rest.Context) (rest.Response, error) {
	logger := log.WithField(ctx, "KnowledgeBaseDetailHandler.Post", "start")

	var request KnowledgeBaseDetailRequest
	if err := ctx.JSONArgs(&request); err != nil {
		logger.Errorf(ctx, "failed to parse request: %v", err)
		return nil, err
	}

	if request.Limit <= 0 {
		request.Limit = 2000 // 默认限制为2000
	}

	// 调用知识库详情服务
	response := h.aiIngressRPC.ConcurrentGetKnowledgeBaseDetail(ctx, request.MemberId, request.KnowledgeBaseIds, request.Limit, 10)

	return ResponseSuccess(response)
}
