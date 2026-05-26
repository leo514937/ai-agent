package impl

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type HotContentProductDAOImpl struct {
}

var DefaultHotContentProductDAO dao.HotContentProductDAO

func NewHotContentProductDAOImpl() *HotContentProductDAOImpl {
	return &HotContentProductDAOImpl{}
}

func init() {
	DefaultHotContentProductDAO = NewHotContentProductDAOImpl()
}

type PDate struct {
	Pdate string `borm:"column:p_date"`
}

func (h *HotContentProductDAOImpl) buildCondition(db *borm.ORM, filterParams *model.HotContentFilterParams, pDate string) *borm.ORM {
	if filterParams.BayesFirstCategoryName != "" {
		db = db.Where(borm.Eq{"bayes_firstcategory_name": filterParams.BayesFirstCategoryName})
	}
	if filterParams.FirstLevelTop != "" {
		db = db.Where(borm.Eq{"first_level_top": filterParams.FirstLevelTop})
	}
	if filterParams.SecondLevelTop != "" {
		db = db.Where(borm.Eq{"second_level_top": filterParams.SecondLevelTop})
	}
	if filterParams.EntityName != "" {
		db = db.Where(borm.Eq{"entity_name": filterParams.EntityName})
	}
	if filterParams.EntityScoreLowerBound > 0 {
		db = db.Where(borm.GTE{"entity_score": filterParams.EntityScoreLowerBound})
	}
	if filterParams.EntityScoreUpperBound > 0 {
		db = db.Where(borm.LTE{"entity_score": filterParams.EntityScoreUpperBound})
	}

	db = db.Where(borm.Eq{"p_date": pDate})
	return db
}

func (h *HotContentProductDAOImpl) FindByFilterParams(ctx context.Context, filterParams *model.HotContentFilterParams) ([]*model.HotContentProducts, int64, string, error) {
	db := mysql.AispInternalBorm

	tableName := (&model.HotContentProducts{}).TableName()
	var pdate = &PDate{}
	err := db.SQL(fmt.Sprintf("select p_date from %s order by p_date desc limit 1", tableName)).ScanOne(ctx, pdate)
	if err != nil {
		log.Errorf(ctx, "get p_date error. err=%v", err)
		return nil, 0, "", err
	}

	log.Infof(ctx, "get %s pdate=%v", tableName, pdate.Pdate)

	var products = make([]*model.HotContentProducts, 0)

	db = h.buildCondition(db, filterParams, pdate.Pdate)
	db = db.OrderBy("entity_rank").Offset(filterParams.Page * filterParams.PageSize).Limit(filterParams.PageSize)

	err = db.All(ctx, &products)
	if err != nil {
		log.WithField(ctx, "filterParams", filterParams).Errorf(ctx, "FindByFilterParams err. err=%v", err)
		return nil, 0, pdate.Pdate, err
	}

	cnt, err := h.buildCondition(db, filterParams, pdate.Pdate).
		Model(&model.HotContentProducts{}).
		Count(ctx)
	if err != nil {
		log.WithField(ctx, "filterParams", filterParams).Errorf(ctx, "FindByFilterParams get count err. err=%v", err)
		return nil, 0, pdate.Pdate, err
	}

	return products, cnt, pdate.Pdate, nil
}

func (h *HotContentProductDAOImpl) FindTrendByFilterParams(ctx context.Context, filterParams *model.HotContentFilterParams) ([]*model.HotContentProductScore, error) {
	db := mysql.AispInternalBorm

	var args []any
	sql := "select sum(entity_score) as product_score, p_date from hot_extract_products_ranking_evaluation where p_date >= ? and p_date <= ? "
	args = append(args, filterParams.PDateStart, filterParams.PDateEnd)
	if filterParams.BayesFirstCategoryName != "" {
		sql += "and bayes_firstcategory_name = ?"
		args = append(args, filterParams.BayesFirstCategoryName)
	}
	if filterParams.FirstLevelTop != "" {
		sql += "and first_level_top = ?"
		args = append(args, filterParams.FirstLevelTop)
	}
	if filterParams.SecondLevelTop != "" {
		sql += "and second_level_top = ?"
		args = append(args, filterParams.SecondLevelTop)
	}
	if filterParams.EntityName != "" {
		sql += "and entity_name = ?"
		args = append(args, filterParams.EntityName)
	}
	if filterParams.EntityScoreLowerBound > 0 {
		sql += "and entity_score >= ?"
		args = append(args, filterParams.EntityScoreLowerBound)
	}
	if filterParams.EntityScoreUpperBound > 0 {
		sql += "and entity_score <= ?"
		args = append(args, filterParams.EntityScoreUpperBound)
	}
	sql += "group by p_date order by p_date"
	stmt, err := db.PrepareContext(ctx, sql)
	log.Infof(ctx, "FindTrendByFilterParams sql=%s, args=%v", sql, args)
	if err != nil {
		log.WithField(ctx, "filterParams", filterParams).Errorf(ctx, "FindTrendByFilterParams PrepareContext err. err=%v", err)
		return nil, err
	}

	rows, err := stmt.QueryContext(ctx, args...)
	if err != nil {
		log.WithField(ctx, "filterParams", filterParams).Errorf(ctx, "FindTrendByFilterParams QueryContext err. err=%v", err)
		return nil, err
	}

	var products = make([]*model.HotContentProductScore, 0)

	for rows.Next() {
		var product model.HotContentProductScore
		err = rows.Scan(&product.ProductScore, &product.PDate)
		if err != nil {
			log.WithField(ctx, "filterParams", filterParams).Errorf(ctx, "FindTrendByFilterParams Scan err. err=%v", err)
			return nil, err
		}
		products = append(products, &product)
	}

	return products, nil
}

func (h *HotContentProductDAOImpl) DeleteByPDate(ctx context.Context, pdate string) error {
	db := mysql.AispInternalBorm

	deleteSize := 1000
	page := 0
	for {
		filterParams := &model.HotContentFilterParams{
			Page:     page,
			PageSize: deleteSize,
		}

		// 删除
		result := db.Table("hot_extract_products_ranking_evaluation").Where(borm.Eq{"p_date": pdate}).Limit(filterParams.PageSize).DeleteRaw(ctx)
		if result.Error != nil {
			log.Errorf(ctx, "DeleteByPDate Delete err. err=%v", result.Error)
			return result.Error
		}

		if result.AffectedRows == 0 {
			log.Infof(ctx, "DeleteByPDate Delete finish. pdate=%s", pdate)
			break
		}

		log.Infof(ctx, "DeleteByPDate Deleting. pdate=%s, page=%d", pdate, page)
		time.Sleep(100 * time.Millisecond)
		page++
	}

	return nil
}
