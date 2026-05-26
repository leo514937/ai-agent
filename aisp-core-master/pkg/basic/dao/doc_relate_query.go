package dao

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

type DocRelateQueryDao interface {
	SetDocRelateQueries(ctx context.Context, docId int64, docType content.DocType_Type, questions []string) bool
	GetDocRelateQueries(ctx context.Context, docId int64, docType content.DocType_Type) []string
	SetDocIndex2QueriesIndex(ctx context.Context, docIndex int64, queriesIndex []int64) bool
	GetDocIndex2QueriesIndex(ctx context.Context, docIndex int64) []int64
}
