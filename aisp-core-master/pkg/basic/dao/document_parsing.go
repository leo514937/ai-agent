package dao

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type DocumentParsingDao interface {
	GetDocumentParsing(ctx context.Context, docId int64, docType content.DocType_Type, processorName string) (*model.DocumentParsingBase, error)
	InsertDocumentParsing(ctx context.Context, documentParsing *model.DocumentParsingBase) error
	UpdateDocumentParsing(ctx context.Context, documentParsing *model.DocumentParsingBase) error
}
