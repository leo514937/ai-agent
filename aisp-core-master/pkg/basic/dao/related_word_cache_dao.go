package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
)

type RelatedWordCacheKey string

type RelatedWordCacheDao interface {
	SaveCache(ctx context.Context, scene string, key RelatedWordCacheKey, values []*entities.Item) error
	GetCache(ctx context.Context, scene string, key RelatedWordCacheKey) ([]*entities.Item, error)
	RemoveCache(ctx context.Context, scene string, key RelatedWordCacheKey) error

	// =========== 创建Key ===========

	CreateAskCacheKey(doc model.Content) RelatedWordCacheKey
	CreateSearchAskCacheKey(memberId int64, query string) RelatedWordCacheKey
}
