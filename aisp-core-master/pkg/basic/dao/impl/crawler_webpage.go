package impl

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type CrawlerWebpageDaoImpl struct {
	db *borm.ORM
}

var DefaultCrawlerWebpageDao dao.CrawlerWebpageDao

func init() {
	DefaultCrawlerWebpageDao = NewCrawlerWebpageDao()
}

func NewCrawlerWebpageDao() dao.CrawlerWebpageDao {
	return &CrawlerWebpageDaoImpl{
		db: mysql.CrawlerWebPageBorm,
	}
}

// BatchUpsert 批量插入，存在的话就更新
func (c *CrawlerWebpageDaoImpl) BatchUpsert(ctx context.Context, webs []*model.CrawlerWebPage) error {
	var insertResult = c.db.DuplicateCols([]string{
		"object_id",
		"title",
		"meta_url",
		"source",
		"source_level",
		"content",
		"domain",
		"publish_time",
		"is_crawler_allowed",
		"crawler_time",
		"extra_info",
	}).CreateMany(ctx, webs)
	if insertResult.Error != nil {
		return insertResult.Error
	}
	return nil
}

func (c *CrawlerWebpageDaoImpl) BatchGet(ctx context.Context, keys []*model.CrawlerWebPageKey) ([]*model.CrawlerWebPage, error) {
	webPages := make([]*model.CrawlerWebPage, 0)

	conditions := make(borm.OR, 0)
	for _, key := range keys {
		conditions = append(conditions, borm.Eq{
			`doc_id`:   key.DocId,
			`doc_type`: key.DocType,
		})
	}

	err := c.db.Where(conditions).All(ctx, &webPages)
	if err != nil {
		return webPages, err
	}

	return webPages, nil
}
