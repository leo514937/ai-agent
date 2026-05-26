package dao

import (
	"context"
	"database/sql"
	"errors"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
)

// CREATE TABLE IF NOT EXISTS `arena` (
//
//	`id` bigint(20) NOT NULL AUTO_INCREMENT COMMENT '自增ID',
//	`name` varchar(255) NOT NULL COMMENT '竞技场名称',
//	`owner_email` varchar(255) NOT NULL COMMENT '竞技场所有者邮箱',
//	`gladiators` mediumtext NOT NULL COMMENT '竞技场中的角色配置 (JSON)',
//	PRIMARY KEY (`id`)
//
// ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
type ArenaDAO interface {
	CreateArena(ctx context.Context, arena *domainModel.Arena) (int64, error)
	GetArenaByID(ctx context.Context, arenaID int64) (*domainModel.Arena, error)
	UpdateArena(ctx context.Context, arena *domainModel.Arena) error
	UpdateArenaState(ctx context.Context, id int64, state domainModel.ArenaState) error
	ListArena(ctx context.Context, offset, limit int64) ([]*domainModel.Arena, error)
	CountArena(ctx context.Context) (int64, error)
}

var (
	DefaultArenaDAO ArenaDAO = NewArenaDAOImpl()
	_               ArenaDAO = (*ArenaDAOImpl)(nil)
)

type ArenaDAOImpl struct {
	conn      mysql.Connection
	tableName string
	columns   []string
}

func NewArenaDAOImpl() *ArenaDAOImpl {
	return &ArenaDAOImpl{
		conn:      resource.MySQLAISPInternal,
		tableName: "arena",
		columns: []string{
			"id",
			"name_",
			"owner_email",
			"state_",
			"gladiators",
			"result",
		},
	}
}

func (d *ArenaDAOImpl) CreateArena(ctx context.Context, arena *domainModel.Arena) (int64, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "basic.dao.ArenaDAOImpl.CreateArena",
		"arena": arena,
	})

	query, args, err := sq.
		Insert(d.tableName).
		SetMap(map[string]interface{}{
			"id":          arena.ID,
			"name_":       arena.Name,
			"owner_email": arena.OwnerEmail,
			"state_":      arena.State,
			"gladiators":  utils.MustMarshalToString(arena.Gladiators),
			"result":      arena.Result,
		}).
		ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to generate sql")
		return 0, err
	}
	result, err := d.conn.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to execute sql")
		return 0, err
	}
	arena.ID, err = result.LastInsertId()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to get last insert id")
		return 0, err
	}
	logger.WithField(ctx, "id", arena.ID).Info(ctx, "arena created")
	return arena.ID, nil
}

func (d *ArenaDAOImpl) GetArenaByID(ctx context.Context, arenaID int64) (arena *domainModel.Arena, err error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":    "basic.dao.ArenaDAOImpl.GetArenaByID",
		"arenaID": arenaID,
	})

	query, args, err := sq.
		Select(d.columns...).
		From(d.tableName).
		Where(sq.Eq{"id": arenaID}).
		ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to generate sql")
		return nil, err
	}
	arena, err = d.scanArena(ctx, d.conn.QueryRow(ctx, query, args...))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	return arena, nil
}

func (d *ArenaDAOImpl) scanArena(ctx context.Context, scanner sq.RowScanner) (*domainModel.Arena, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.dao.ArenaDAOImpl.scanArena",
	})
	arena := &domainModel.Arena{}
	rawGladiators := ""
	result := sql.NullString{}
	err := scanner.Scan(&arena.ID, &arena.Name, &arena.OwnerEmail, &arena.State, &rawGladiators, &result)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to scan row")
		return nil, err
	}
	err = utils.JSONUnmarshal([]byte(rawGladiators), &arena.Gladiators)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to unmarshal gladiators")
		return nil, err
	}
	arena.Result = result.String
	return arena, nil
}

func (d *ArenaDAOImpl) UpdateArena(ctx context.Context, arena *domainModel.Arena) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "basic.dao.ArenaDAOImpl.UpdateArena",
		"arena": arena,
	})
	updates := map[string]interface{}{
		"name_":       arena.Name,
		"owner_email": arena.OwnerEmail,
		"state_":      arena.State,
		"gladiators":  utils.MustMarshalToString(arena.Gladiators),
		"result":      arena.Result,
	}
	if arena.Result == "" {
		delete(updates, "result")
	}
	if arena.State == "" {
		delete(updates, "state_")
	}
	query, args, err := sq.
		Update(d.tableName).
		SetMap(updates).
		Where(sq.Eq{"id": arena.ID}).
		ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to generate sql")
		return err
	}
	_, err = d.conn.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to execute sql")
		return err
	}
	logger.Info(ctx, "arena updated")
	return nil
}

func (d *ArenaDAOImpl) UpdateArenaState(ctx context.Context, id int64, state domainModel.ArenaState) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":  "basic.dao.ArenaDAOImpl.UpdateArenaState",
		"id":    id,
		"state": state,
	})
	query, args, err := sq.
		Update(d.tableName).
		SetMap(map[string]interface{}{
			"state_": state,
		}).
		Where(sq.Eq{"id": id}).
		ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to generate sql")
		return err
	}
	_, err = d.conn.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to execute sql")
		return err
	}
	logger.Info(ctx, "arena state updated")
	return nil
}

func (d *ArenaDAOImpl) ListArena(ctx context.Context, offset, limit int64) ([]*domainModel.Arena, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":   "basic.dao.ArenaDAOImpl.ListArena",
		"offset": offset,
		"limit":  limit,
	})

	query, args, err := sq.
		Select(d.columns...).
		From(d.tableName).
		OrderBy("created_at DESC", "id DESC").
		Offset(uint64(offset)).
		Limit(uint64(limit)).
		ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to generate sql")
		return nil, err
	}
	rows, err := d.conn.Query(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to execute sql")
		return nil, err
	}
	defer rows.Close()
	arenas := []*domainModel.Arena{}
	for rows.Next() {
		arena, err := d.scanArena(ctx, rows)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to scan row")
			return nil, err
		}
		arenas = append(arenas, arena)
	}
	if rows.Err() != nil {
		logger.WithError(ctx, rows.Err()).Error(ctx, "failed to scan row")
		return nil, rows.Err()
	}
	return arenas, nil
}

func (d *ArenaDAOImpl) CountArena(ctx context.Context) (int64, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "basic.dao.ArenaDAOImpl.CountArena",
	})

	query, args, err := sq.
		Select("COUNT(*)").
		From(d.tableName).
		ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to generate sql")
		return 0, err
	}
	var count int64
	err = d.conn.QueryRow(ctx, query, args...).Scan(&count)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to execute sql")
		return 0, err
	}
	return count, nil
}
