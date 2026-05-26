package dao

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
)

type DigitalAuthorIndexDao interface {
	SetOnSiteIndexStatus(ctx context.Context, docId int64, docType content.DocType_Type, status bool) error
	GetOnSiteIndexStatus(ctx context.Context, docId int64, docType content.DocType_Type) (bool, error)
}
