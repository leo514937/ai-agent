package dao

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type KnowledgeBaseV2Dao interface {
	// CreateKnowledgeBase 【知识库】创建知识库
	CreateKnowledgeBase(ctx context.Context, knowledgeBase *model.KnowledgeBase) error
	// DeleteKnowledgeBase 【知识库】删除知识库
	DeleteKnowledgeBase(ctx context.Context, knowledgeBaseId int64) error
	// IsDocumentUrlExist 【文档】判断文档是否存在
	IsDocumentUrlExist(ctx context.Context, url string) (*model.DocumentInfo, bool)
	// IsDocumentIdExist 【文档】判断文档是否存在
	IsDocumentIdExist(ctx context.Context, docId int64, docType string) (int64, bool)
	// UpsertDocument 【文档】用 doc_id、doc_type 进行 upsert
	UpsertDocument(ctx context.Context, documentInfo *model.DocumentInfo) error
	// GetDocumentInfo 【文档】获取文档信息
	GetDocumentInfo(ctx context.Context, docId int64, docType content.DocType_Type) *model.DocumentInfo
	// DeleteDocument 【文档】删除文档
	DeleteDocument(ctx context.Context, docId int64, docType string) error
	// AddKnowledgeBaseDocument 【知识库-文档】添加知识库文档
	AddKnowledgeBaseDocument(ctx context.Context, knowledgeBaseDoc *model.KnowledgeBaseDocV2) error
	// DeleteKnowledgeBaseDocument 【知识库-文档】删除知识库文档
	DeleteKnowledgeBaseDocument(ctx context.Context, knowledgeBaseDoc *model.KnowledgeBaseDocV2) error
	// GetKnowledgeBaseDocument 【知识库-文档】获取知识库下文档列表
	GetKnowledgeBaseDocument(ctx context.Context, knowledgeBaseId int64, knowledgeBaseType proto.PersonalKnowledgeBaseType) ([]*model.KnowledgeBaseDocV2, error)
}
