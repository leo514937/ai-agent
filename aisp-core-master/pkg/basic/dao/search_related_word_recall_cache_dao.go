package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type SearchRelatedWordRecallCacheDao interface {
	SaveCache(ctx context.Context, scene string, memberId int64, query string, values []model.Content) error
	GetCache(ctx context.Context, scene string, memberId int64, query string) ([]model.Content, error)
	RemoveCache(ctx context.Context, scene string, memberId int64, query string) error
}
