package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

const pDateFormat = "2006-01-02"

var DefaultCrawledWebDao dao.CrawledWebPageDao

func init() {
	DefaultCrawledWebDao = NewCrawledWebDao()
}

type CrawledWebDaoImpl struct {
}

func NewCrawledWebDao() dao.CrawledWebPageDao {
	return &CrawledWebDaoImpl{}
}

// BatchInsert 批量插入
func (d *CrawledWebDaoImpl) BatchInsert(ctx context.Context, webs []*model.CrawledWebPage) (mysql.Result, error) {
	db := mysql.AispInternalBorm
	now := time.Now()
	for _, web := range webs {
		if web.CrawlAt == nil {
			web.CrawlAt = &now
		}
	}
	var insertResult = db.CreateMany(ctx, webs)
	if insertResult.Error != nil {
		return mysql.Result{}, insertResult.Error
	}
	return mysql.Result{LastInsertedID: insertResult.LastInsertedID, AffectedRows: insertResult.AffectedRows}, nil
}

func (d *CrawledWebDaoImpl) Update(ctx context.Context, webPage *model.CrawledWebPage) error {
	db := mysql.AispInternalBorm

	params := map[string]interface{}{
		"raw_content": webPage.RawContent,
		"title":       webPage.Title,
	}

	var insertResult = db.Model(&webPage).Updates(ctx, params)
	if insertResult.Error != nil {
		log.Errorf(ctx, "update failed. url=%s. err=%+v", webPage.Url, insertResult.Error)
		return insertResult.Error
	}

	return nil
}

func (d *CrawledWebDaoImpl) BatchGetCrawled(ctx context.Context, urlHashs []int64, beginPDate time.Time, endPDate time.Time, limit int) ([]*model.CrawledWebPage, error) {
	db := mysql.AispInternalBorm

	webPages := make([]*model.CrawledWebPage, 0)
	err := db.Where(borm.Eq{
		`url_hash`: urlHashs,
	}).Where(borm.GTE{
		`p_date`: beginPDate.Format(pDateFormat),
	}).Where(borm.LTE{
		"p_date": endPDate.Format(pDateFormat),
	}).Where(borm.GTE{
		"crawl_at": beginPDate,
	}).Limit(limit).All(ctx, &webPages)

	if err != nil {
		return nil, err
	}
	return webPages, nil
}
