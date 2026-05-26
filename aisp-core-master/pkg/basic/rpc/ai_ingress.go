package rpc

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	knowledge "git.in.zhihu.com/one-rpc-go/thrift-ai_ingress/knowledge_thrift"
)

type AiIngressRPC interface {
	// 获取知识库详细信息
	GetKnowledgeBaseDetail(ctx context.Context, memberId int64, knowledgeBaseId int64, limit int64) *knowledge.GetKnowledgeResponse
	ConcurrentGetKnowledgeBaseDetail(ctx context.Context, memberId int64, knowledgeBaseIds []int64, limit int64, concurrency int) map[int64]*knowledge.GetKnowledgeResponse
	// 获取知识库可见性
	BatchGetKnowledgeBaseVisibility(ctx context.Context, knowledgeBaseIds []int64) map[int64]proto.KnowledgeBaseVisibility
	// 获取操作配置
	GetOperationConfig(ctx context.Context, operationId int64) string
}
