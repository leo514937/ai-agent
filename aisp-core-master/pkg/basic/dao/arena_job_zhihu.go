package dao

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
	"github.com/samber/lo"
)

type ArenaJobDAO interface {
	CreateArenaJob(ctx context.Context, job *domainModel.ArenaJob) (int64, error)
	GetArenaJobByID(ctx context.Context, jobID int64) (*domainModel.ArenaJob, error)
	UpdateArenaJob(ctx context.Context, job *domainModel.ArenaJob) error
	UpdateArenaJobState(ctx context.Context, jobID int64, state domainModel.ArenaJobState) error
	ListArenaJobByArenaID(ctx context.Context, arenaID int64, offset, limit int64) ([]*domainModel.ArenaJob, error)
}

// CREATE TABLE `arena_job` (
//   `id` bigint(20) unsigned NOT NULL AUTO_INCREMENT,
//   `arena_id` bigint(20) unsigned NOT NULL,
//   `arena_snapshot` json NOT NULL,
//   `state_` varchar(255) NOT NULL,
//   `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
//   `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
//   PRIMARY KEY (`id`),
//   KEY `idx_arena_id_state` (`arena_id`, `state_`),
// ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

var (
	DefaultArenaJobDAO ArenaJobDAO = NewArenaJobDAOImpl()
	_                  ArenaJobDAO = (*ArenaJobDAOImpl)(nil)
)

type ArenaJobDAOImpl struct {
	conn      mysql.Connection
	tableName string
	columns   []string
}

func NewArenaJobDAOImpl() *ArenaJobDAOImpl {
	return &ArenaJobDAOImpl{
		conn:      resource.MySQLAISPInternal,
		tableName: "arena_job",
		columns: []string{
			"id",
			"arena_id",
			"arena_snapshot",
			"state_",
			"created_at",
			"updated_at",
		},
	}
}

func (d *ArenaJobDAOImpl) CreateArenaJob(ctx context.Context, job *domainModel.ArenaJob) (int64, error) {
	logger := log.WithFields(ctx, log.Fields{
		"func": "pkg.core.dao.arena_job.CreateArenaJob",
		"job":  job,
	})
	query, args, err := sq.
		Insert(d.tableName).
		SetMap(map[string]any{
			"arena_id":       job.ArenaID,
			"arena_snapshot": string(lo.Must(json.Marshal(job.ArenaSnapshot))),
			"state_":         job.State,
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
	logger.WithField("id", id).Info("success to create arena job")
	return id, nil
}

func (d *ArenaJobDAOImpl) GetArenaJobByID(ctx context.Context, jobID int64) (*domainModel.ArenaJob, error) {
	logger := log.WithFields(ctx, log.Fields{
		"func":  "pkg.core.dao.arena_job.GetArenaJobByID",
		"jobID": jobID,
	})
	query, args, err := sq.
		Select(d.columns...).
		From(d.tableName).
		Where(sq.Eq{"id": jobID}).
		ToSql()
	if err != nil {
		logger.WithError(err).Error("failed to generate sql")
		return nil, err
	}
	row := d.conn.QueryRow(ctx, query, args...)
	job, err := d.scanArenaJob(row)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		logger.WithError(err).Error("failed to scan arena job")
		return nil, err
	}
	return job, nil
}

func (d *ArenaJobDAOImpl) UpdateArenaJob(ctx context.Context, job *domainModel.ArenaJob) error {
	logger := log.WithFields(ctx, log.Fields{
		"func": "pkg.core.dao.arena_job.UpdateArenaJob",
		"job":  job,
	})
	query, args, err := sq.
		Update(d.tableName).
		SetMap(map[string]any{
			"arena_id":       job.ArenaID,
			"arena_snapshot": string(lo.Must(json.Marshal(job.ArenaSnapshot))),
			"state_":         job.State,
		}).
		Where(sq.Eq{"id": job.ID}).
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
	logger.Info("success to update arena job")
	return nil
}

func (d *ArenaJobDAOImpl) UpdateArenaJobState(ctx context.Context, jobID int64, state domainModel.ArenaJobState) error {
	logger := log.WithFields(ctx, log.Fields{
		"func":   "pkg.core.dao.arena_job.UpdateArenaJobState",
		"job_id": jobID,
		"state":  state,
	})
	query, args, err := sq.
		Update(d.tableName).
		Set("state_", state).
		Where(sq.Eq{"id": jobID}).
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
	logger.Info("success to update arena job state")
	return nil
}

func (d *ArenaJobDAOImpl) scanArenaJob(scanner sq.RowScanner) (*domainModel.ArenaJob, error) {
	var (
		job         domainModel.ArenaJob
		rawSnapshot []byte
	)
	if err := scanner.Scan(
		&job.ID,
		&job.ArenaID,
		&rawSnapshot,
		&job.State,
		&job.CreatedAt,
		&job.UpdatedAt,
	); err != nil {
		return nil, err
	}
	err := util.JSONUnmarshal(rawSnapshot, &job.ArenaSnapshot)
	if err != nil {
		return nil, err
	}
	return &job, nil
}

func (d *ArenaJobDAOImpl) ListArenaJobByArenaID(ctx context.Context, arenaID int64, offset, limit int64) ([]*domainModel.ArenaJob, error) {
	logger := log.WithFields(ctx, log.Fields{
		"func":    "pkg.core.dao.arena_job.ListArenaJobByArenaID",
		"arenaID": arenaID,
		"offset":  offset,
		"limit":   limit,
	})
	query, args, err := sq.
		Select(d.columns...).
		From(d.tableName).
		Where(sq.Eq{"arena_id": arenaID}).
		OrderBy("created_at DESC").
		Limit(uint64(limit)).
		Offset(uint64(offset)).
		ToSql()
	if err != nil {
		logger.WithError(err).Error("failed to generate sql")
		return nil, err
	}
	rows, err := d.conn.Query(ctx, query, args...)
	if err != nil {
		logger.WithError(err).Error("failed to execute sql")
		return nil, err
	}
	defer rows.Close()
	var jobs []*domainModel.ArenaJob
	for rows.Next() {
		job, err := d.scanArenaJob(rows)
		if err != nil {
			logger.WithError(err).Error("failed to scan arena job")
			return nil, err
		}
		jobs = append(jobs, job)
	}
	if err := rows.Err(); err != nil {
		logger.WithError(err).Error("failed to scan arena job")
		return nil, err
	}
	return jobs, nil
}
