package dao

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type CrawledWebPageDao interface {
	BatchInsert(ctx context.Context, webs []*model.CrawledWebPage) (mysql.Result, error)
	Update(ctx context.Context, web *model.CrawledWebPage) error
	BatchGetCrawled(ctx context.Context, urlHashs []int64, beginPDate time.Time, endPDate time.Time, limit int) ([]*model.CrawledWebPage, error)
}
