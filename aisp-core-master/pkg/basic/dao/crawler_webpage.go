package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

// CrawlerWebpageDao 自建搜索引擎的正排数据
type CrawlerWebpageDao interface {
	BatchUpsert(ctx context.Context, webs []*model.CrawlerWebPage) error
	BatchGet(ctx context.Context, keys []*model.CrawlerWebPageKey) ([]*model.CrawlerWebPage, error)
}
