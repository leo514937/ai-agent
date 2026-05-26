package dao

import (
	"context"
	"database/sql"
	"errors"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
)

type DailySnapshotDAO interface {
	GetDailySnapshotDateByUserIDOrderByDate(ctx context.Context, userID int64) ([]string, error)
	GetDailySnapshotByUserIDAndDate(ctx context.Context, userID int64, date string) (*model.TableDailySnapshot, error)
	GetDailySnapshotsByUserIDBetweenDate(ctx context.Context, userID int64, startDate, endDate string) ([]*model.TableDailySnapshot, error)
	GetDailySnapshotByHashToken(ctx context.Context, hashToken string) (*model.TableDailySnapshot, error)
	CreateDailySnapshot(ctx context.Context, dataMap map[string]interface{}) error
}

type DailySnapshotDAOImpl struct {
	connection mysql.Connection
}

func newDailySnapshotDAOImpl() DailySnapshotDAO {
	return &DailySnapshotDAOImpl{
		connection: resource.MySQLAISPCore,
	}
}

var DefaultDailySnapshotDAO DailySnapshotDAO

func init() {
	DefaultDailySnapshotDAO = newDailySnapshotDAOImpl()
}

func (d *DailySnapshotDAOImpl) CreateDailySnapshot(ctx context.Context, dataMap map[string]interface{}) error {
	query, args, err := sq.
		Insert((&model.TableDailySnapshot{}).TableName()).
		SetMap(dataMap).
		ToSql()
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[CreateDailySnapshot] failed to generate sql.err=%v", err)
		return err
	}
	_, err = d.connection.Exec(ctx, query, args...)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[CreateDailySnapshot] failed to exec sql.err=%v", err)
		return err
	}
	return nil
}

func (d *DailySnapshotDAOImpl) GetDailySnapshotDateByUserIDOrderByDate(ctx context.Context, userID int64) ([]string, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"user_id": userID,
	})
	var dates []string
	query, args, err := sq.Select("generate_date").From((&model.TableDailySnapshot{}).TableName()).Where(sq.Eq{"user_id": userID}).OrderBy("generate_date DESC").ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotByUserID] failed to build sql")
		return nil, err
	}
	rows, err := d.connection.Query(ctx, query, args...)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return dates, nil
		}
		logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotByUserID] failed to query")
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var date string
		err = rows.Scan(
			&date,
		)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotByUserID] failed to scan")
			return nil, err
		}
		dates = append(dates, date)
	}
	return dates, nil
}

func (d *DailySnapshotDAOImpl) GetDailySnapshotByUserIDAndDate(ctx context.Context, userID int64, date string) (*model.TableDailySnapshot, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"user_id": userID,
		"date":    date,
	})
	// 构建选择查询的 SQL
	querySql, args, err := sq.Select([]string{"user_id", "hash_token", "title", "generate_date", "json_content"}...).From((&model.TableDailySnapshot{}).TableName()).Where(
		sq.And{
			sq.Eq{
				"user_id": userID,
			}, sq.Eq{
				"generate_date": date,
			},
		}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotByUserIDAndDate] failed to build sql")
		return nil, err
	}

	// 执行选择查询
	row := d.connection.QueryRow(ctx, querySql, args...)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, nil
		}
		logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotByUserIDAndDate] failed to QueryRow")
		return nil, err
	}
	if row == nil {
		return nil, nil
	}
	data := &model.TableDailySnapshot{}
	err = row.Scan(
		&data.UserID,
		&data.HashToken,
		&data.Title,
		&data.GenerateDate,
		&data.JsonContent,
	)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, nil
		}
		return nil, err
	}
	return data, nil
}

func (d *DailySnapshotDAOImpl) GetDailySnapshotsByUserIDBetweenDate(ctx context.Context, userID int64, startDate, endDate string) ([]*model.TableDailySnapshot, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"user_id":    userID,
		"start_date": startDate,
		"end_date":   endDate,
	})
	// 构建选择查询的 SQL
	querySql, args, err := sq.Select([]string{"generate_date", "json_content"}...).From((&model.TableDailySnapshot{}).TableName()).Where(sq.And{
		sq.Eq{
			"user_id": userID,
		}, sq.GtOrEq{
			"generate_date": startDate,
		}, sq.LtOrEq{
			"generate_date": endDate,
		},
	},
	).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotsByUserIDBetweenDate] failed to build sql")
		return nil, err
	}
	var contents []*model.TableDailySnapshot
	rows, err := d.connection.Query(ctx, querySql, args...)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return contents, nil
		}
		logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotsByUserIDBetweenDate] failed to query")
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		snapshot := &model.TableDailySnapshot{}
		err = rows.Scan(
			&snapshot.GenerateDate,
			&snapshot.JsonContent,
		)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotsByUserIDBetweenDate] failed to scan")
			return nil, err
		}
		contents = append(contents, snapshot)
	}
	return contents, nil
}

func (d *DailySnapshotDAOImpl) GetDailySnapshotByHashToken(ctx context.Context, hashToken string) (*model.TableDailySnapshot, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"token": hashToken,
	})
	// 构建选择查询的 SQL
	querySql, args, err := sq.Select([]string{"user_id", "hash_token", "title", "generate_date", "json_content"}...).From((&model.TableDailySnapshot{}).TableName()).Where(
		sq.Eq{
			"hash_token": hashToken,
		}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotByHashToken] failed to build sql")
		return nil, err
	}

	// 执行选择查询
	row := d.connection.QueryRow(ctx, querySql, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "[GetDailySnapshotByHashToken] failed to QueryRow")
		return nil, err
	}
	if row == nil {
		return nil, nil
	}
	data := &model.TableDailySnapshot{}
	err = row.Scan(
		&data.UserID,
		&data.HashToken,
		&data.Title,
		&data.GenerateDate,
		&data.JsonContent,
	)
	if err != nil {
		return nil, err
	}
	return data, nil
}
