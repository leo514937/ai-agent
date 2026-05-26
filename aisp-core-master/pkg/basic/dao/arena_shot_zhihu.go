package dao

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
	"github.com/samber/lo"
)

type ArenaShotDAO interface {
	CreateArenaShot(ctx context.Context, shot *domainModel.ArenaShot) (int64, error)
	GetArenaShotByID(ctx context.Context, shotID int64) (*domainModel.ArenaShot, error)
	UpdateArenaShot(ctx context.Context, shot *domainModel.ArenaShot) error
	ListArenaShotByJobID(ctx context.Context, jobID int64, state domainModel.ArenaShotState, offset, limit int64) ([]*domainModel.ArenaShot, error)
	LockArenaShot(ctx context.Context) (*domainModel.ArenaShot, error)
	CountArenaShotByJobID(ctx context.Context, jobID int64, state domainModel.ArenaShotState) (int64, error)
}

// CREATE TABLE `arena_shot` (
//   `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
//   `job_id` bigint(20) unsigned NOT NULL,
//   `state_` varchar(255) NOT NULL,
//   `input` json NOT NULL,
//   `output` json NOT NULL,
//   `error` varchar(255) NOT NULL,
//   `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
//   `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
//   PRIMARY KEY (`id`),
//   KEY `idx_job_id_state` (`job_id`, `state_`),
// ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

type ArenaShotDAOImpl struct {
	conn      mysql.Connection
	tableName string
	columns   []string
}

var (
	DefaultArenaShotDAO ArenaShotDAO = NewArenaShotDAOImpl()
	_                   ArenaShotDAO = (*ArenaShotDAOImpl)(nil)
)

func NewArenaShotDAOImpl() *ArenaShotDAOImpl {
	return &ArenaShotDAOImpl{
		conn:      resource.MySQLAISPInternal,
		tableName: "arena_shot",
		columns: []string{
			"id",
			"job_id",
			"state_",
			"input",
			"output",
			"error_",
			"created_at",
			"updated_at",
		},
	}
}

func (d *ArenaShotDAOImpl) CreateArenaShot(ctx context.Context, shot *domainModel.ArenaShot) (int64, error) {
	logger := log.WithFields(ctx, log.Fields{
		"func": "pkg.core.dao.arena_shot.CreateArenaShot",
		"shot": shot,
	})
	query, args, err := sq.
		Insert(d.tableName).
		SetMap(map[string]interface{}{
			"job_id": shot.JobID,
			"state_": shot.State,
			"input":  string(lo.Must(json.Marshal(shot.Input))),
			"output": string(lo.Must(json.Marshal(shot.Output))),
			"error_": errToStr(shot.Error),
		}).
		ToSql()
	if err != nil {
		logger.WithError(err).Error("failed to generate sql")
		return 0, err
	}
	result, err := d.conn.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(err).Error("failed to execute sql")
		return 0, err
	}
	id, err := result.LastInsertId()
	if err != nil {
		logger.WithError(err).Error("failed to get last insert id")
		return 0, err
	}
	logger.WithField("id", id).Info("success to create arena shot")
	return id, nil
}

func errToStr(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func errFromStr(str string) error {
	if str == "" {
		return nil
	}
	return errors.New(str)
}

func (d *ArenaShotDAOImpl) scanArenaShot(scanner sq.RowScanner) (*domainModel.ArenaShot, error) {
	var (
		arenaShot domainModel.ArenaShot
		input     string
		output    string
		errStr    string
	)
	err := scanner.Scan(
		&arenaShot.ID,
		&arenaShot.JobID,
		&arenaShot.State,
		&input,
		&output,
		&errStr,
		&arenaShot.CreatedAt,
		&arenaShot.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	err = json.Unmarshal([]byte(input), &arenaShot.Input)
	if err != nil {
		return nil, err
	}
	err = json.Unmarshal([]byte(output), &arenaShot.Output)
	if err != nil {
		return nil, err
	}
	arenaShot.Error = errFromStr(errStr)
	return &arenaShot, nil
}

func (d *ArenaShotDAOImpl) GetArenaShotByID(ctx context.Context, shotID int64) (*domainModel.ArenaShot, error) {
	logger := log.WithFields(ctx, log.Fields{
		"func":   "pkg.core.dao.arena_shot.GetArenaShotByID",
		"shotID": shotID,
	})
	query, args, err := sq.
		Select(d.columns...).
		From(d.tableName).
		Where(sq.Eq{"id": shotID}).
		ToSql()
	if err != nil {
		logger.WithError(err).Error("failed to generate sql")
		return nil, err
	}
	row := d.conn.QueryRow(ctx, query, args...)
	shot, err := d.scanArenaShot(row)
	if err != nil {
		logger.WithError(err).Error("failed to scan arena shot")
		return nil, err
	}
	return shot, nil
}

func (d *ArenaShotDAOImpl) UpdateArenaShot(ctx context.Context, shot *domainModel.ArenaShot) error {
	logger := log.WithFields(ctx, log.Fields{
		"func": "pkg.core.dao.arena_shot.UpdateArenaShot",
		"shot": shot,
	})
	query, args, err := sq.
		Update(d.tableName).
		SetMap(map[string]interface{}{
			"job_id":     shot.JobID,
			"state_":     shot.State,
			"input":      string(lo.Must(json.Marshal(shot.Input))),
			"output":     string(lo.Must(json.Marshal(shot.Output))),
			"error_":     errToStr(shot.Error),
			"created_at": shot.CreatedAt,
			"updated_at": shot.UpdatedAt,
		}).
		Where(sq.Eq{"id": shot.ID}).
		ToSql()
	if err != nil {
		logger.WithError(err).Error("failed to generate sql")
		return err
	}
	_, err = d.conn.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(err).Error("failed to execute sql")
		return err
	}
	logger.Info("success to update arena shot")
	return nil
}

func (d *ArenaShotDAOImpl) ListArenaShotByJobID(ctx context.Context, arenaID int64, state domainModel.ArenaShotState, offset, limit int64) ([]*domainModel.ArenaShot, error) {
	logger := log.WithFields(ctx, log.Fields{
		"func":    "pkg.core.dao.arena_shot.ListArenaShotByJobID",
		"arenaID": arenaID,
		"state":   state,
		"offset":  offset,
		"limit":   limit,
	})
	sqlBuilder := sq.
		Select(d.columns...).
		From(d.tableName).
		Where(sq.Eq{"job_id": arenaID, "state_": state})

	if offset != 0 {
		sqlBuilder = sqlBuilder.
			Offset(uint64(offset))
	}
	if limit != 0 {
		sqlBuilder = sqlBuilder.
			Limit(uint64(limit))
	}
	query, args, err := sqlBuilder.ToSql()
	if err != nil {
		logger.WithError(err).Error("failed to generate sql")
		return nil, err
	}
	rows, err := d.conn.Query(ctx, query, args...)
	if err != nil {
		logger.WithError(err).Error("failed to execute sql")
		return nil, err
	}
	var shots []*domainModel.ArenaShot
	for rows.Next() {
		shot, err := d.scanArenaShot(rows)
		if err != nil {
			logger.WithError(err).Error("failed to scan arena shot")
			return nil, err
		}
		shots = append(shots, shot)
	}
	return shots, nil
}

func (d *ArenaShotDAOImpl) LockArenaShot(ctx context.Context) (*domainModel.ArenaShot, error) {
	logger := log.WithFields(ctx, log.Fields{
		"func": "pkg.core.dao.arena_shot.LockArenaShot",
	})
	query, args, err := sq.
		Select(d.columns...).
		From(d.tableName).
		Where(sq.Eq{"state_": domainModel.ArenaShotStateWaiting}).
		OrderBy("id ASC").
		Limit(1).
		Suffix("FOR UPDATE").
		ToSql()
	if err != nil {
		logger.WithError(err).Error("failed to generate sql")
		return nil, err
	}
	row := d.conn.QueryRow(ctx, query, args...)
	shot, err := d.scanArenaShot(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		logger.WithError(err).Error("failed to scan arena shot")
		return nil, err
	}
	return shot, nil
}

func (d *ArenaShotDAOImpl) CountArenaShotByJobID(ctx context.Context, jobID int64, state domainModel.ArenaShotState) (int64, error) {
	logger := log.WithFields(ctx, log.Fields{
		"func":  "pkg.core.dao.arena_shot.CountArenaShotByJobID",
		"jobID": jobID,
		"state": state,
	})
	query, args, err := sq.
		Select("COUNT(*)").
		From(d.tableName).
		Where(sq.Eq{"job_id": jobID, "state_": state}).
		ToSql()
	if err != nil {
		logger.WithError(err).Error("failed to generate sql")
		return 0, err
	}
	row := d.conn.QueryRow(ctx, query, args...)
	var count int64
	err = row.Scan(&count)
	if err != nil {
		logger.WithError(err).Error("failed to scan count")
		return 0, err
	}
	return count, nil
}
