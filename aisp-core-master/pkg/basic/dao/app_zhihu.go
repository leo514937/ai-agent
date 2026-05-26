package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
)

type AppDAO interface {
	ListApp(ctx context.Context, name, bizLineName string) ([]*model.App, error)
	ListAllApps(ctx context.Context) ([]*model.App, error)
	ListAllAppsByNames(ctx context.Context, appNames []string) ([]*model.App, error)
	SetAppBizLineName(ctx context.Context, name, bizLineName string) error
}

type AppDAOImpl struct {
	conn mysql.Connection
}

var (
	_             AppDAO = (*AppDAOImpl)(nil)
	DefaultAppDAO AppDAO = NewAppDAO()
)

func NewAppDAO() AppDAO {
	return &AppDAOImpl{
		conn: resource.MySQLAISPInternal,
	}
}

func (d *AppDAOImpl) ListAllApps(ctx context.Context) ([]*model.App, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "dao.AppDAOImpl.ListAllApps",
	})

	query, args, err := sq.
		Select(`app_name`, `owner_pinyin`, `owner_department_name`).
		From(`zae_app`).
		OrderBy(`app_name`).
		ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return nil, err
	}

	rows, err := d.conn.Query(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to query")
		return nil, err
	}
	defer rows.Close()

	apps := []*model.App{}
	for rows.Next() {
		app := &model.App{}
		if err := rows.Scan(&app.Name, &app.OwnerEmail, &app.OwnerBizLineName); err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to scan")
			return nil, err
		}
		apps = append(apps, app)
	}

	return apps, nil
}

func (d *AppDAOImpl) ListAllAppsByNames(ctx context.Context, appNames []string) ([]*model.App, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "dao.AppDAOImpl.ListAllApps",
	})

	builder := sq.
		Select(`app_name`, `owner_pinyin`, `owner_department_name`).
		From(`zae_app`)
	if appNames != nil && len(appNames) != 0 {
		builder = builder.Where(sq.Eq{`app_name`: appNames})
	}
	builder.OrderBy(`app_name`)
	query, args, err := builder.ToSql()

	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return nil, err
	}

	rows, err := d.conn.Query(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to query")
		return nil, err
	}
	defer rows.Close()

	apps := []*model.App{}
	for rows.Next() {
		app := &model.App{}
		if err := rows.Scan(&app.Name, &app.OwnerEmail, &app.OwnerBizLineName); err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to scan")
			return nil, err
		}
		apps = append(apps, app)
	}

	return apps, nil
}

func (d *AppDAOImpl) ListApp(ctx context.Context, name, bizLineName string) ([]*model.App, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":        "dao.AppDAOImpl.ListApp",
		"name":        name,
		"bizLineName": bizLineName,
	})

	query, args, err := sq.
		Select(`app_name`, `owner_pinyin`, `owner_department_name`).
		From(`zae_app`).
		Where(
			sq.And{
				sq.Like{
					`app_name`: `%` + name + `%`,
				},
				sq.Or{
					sq.Eq{
						`owner_department_name`: bizLineName,
					},
					sq.Like{
						`owner_department_name`: bizLineName + `-%`,
					},
					sq.Expr(`? = ''`, bizLineName),
				},
			},
		).
		OrderBy(`app_name`).
		ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return nil, err
	}
	rows, err := d.conn.Query(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to query")
		return nil, err
	}
	defer rows.Close()
	apps := []*model.App{}
	for rows.Next() {
		app := &model.App{}
		if err := rows.Scan(&app.Name, &app.OwnerEmail, &app.OwnerBizLineName); err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to scan")
			return nil, err
		}
		apps = append(apps, app)
	}
	return apps, nil
}

func (d *AppDAOImpl) SetAppBizLineName(ctx context.Context, name, bizLineName string) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func":        "dao.AppDAOImpl.SetAppBizLineName",
		"name":        name,
		"bizLineName": bizLineName,
	})

	query, args, err := sq.
		Update(`zae_app`).
		SetMap(map[string]interface{}{
			`owner_department_name`: bizLineName,
		}).
		Where(sq.Eq{
			`app_name`: name,
		}).
		ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return err
	}
	_, err = d.conn.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to exec")
		return err
	}
	logger.Info(ctx, "success")
	return nil
}
