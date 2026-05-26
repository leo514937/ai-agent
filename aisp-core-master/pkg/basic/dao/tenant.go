package dao

import (
	"context"
	"database/sql"
	"errors"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
)

const tenantTableName = "tenant"

//go:generate mockery --name TenantDAO
type TenantDAO interface {
	GetTenantByID(ctx context.Context, tenantID int64) (*model.Tenant, error)
	CreateTenant(ctx context.Context, tenant *model.Tenant) (int64, error)
	UpdateTenantState(ctx context.Context, tenantID int64, state model.TenantState) error
}

var DefaultTenantDAO TenantDAO

type TenantDAOImpl struct {
	connection mysql.Connection
}

func NewTenantDAOImpl() *TenantDAOImpl {
	return &TenantDAOImpl{
		connection: resource.MySQLAISPCore,
	}
}

var _ TenantDAO = (*TenantDAOImpl)(nil)

func (*TenantDAOImpl) columns() []string {
	// columns of
	// type Tenant struct {
	// 	ID          int64       `json:"id"`
	// 	Owner       string      `json:"owner"`
	// 	Name        string      `json:"name"`
	// 	Description string      `json:"description"`
	// 	State       TenantState `json:"state"`
	// 	CreatedAt   time.Time   `json:"created_at"`
	// 	UpdatedAt   time.Time   `json:"updated_at"`
	// }
	return []string{
		"id",
		"owner_",
		"name_",
		"description_",
		"state",
		"created_at",
		"updated_at",
	}
}

func (*TenantDAOImpl) insertColumns() []string {
	return []string{
		"owner_",
		"name_",
		"description_",
		"state",
	}
}

func (d *TenantDAOImpl) GetTenantByID(ctx context.Context, tenantID int64) (*model.Tenant, error) {
	logger := log.WithField(ctx, "tenantID", tenantID)

	query, args, err := sq.Select(d.columns()...).From(tenantTableName).Where(sq.Eq{"id": tenantID}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return nil, err
	}
	row := d.connection.QueryRow(ctx, query, args...)
	var tenant model.Tenant
	err = row.Scan(
		&tenant.ID,
		&tenant.Owner,
		&tenant.Name,
		&tenant.Description,
		&tenant.State,
		&tenant.CreatedAt,
		&tenant.UpdatedAt,
	)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			logger.Warn(ctx, "tenant not found")
			return nil, nil
		}

		logger.WithError(ctx, err).Error(ctx, "failed to scan row")
		return nil, err
	}
	return &tenant, nil
}

func (d *TenantDAOImpl) CreateTenant(ctx context.Context, tenant *model.Tenant) (int64, error) {
	logger := log.WithField(ctx, "tenant", tenant)

	query, args, err := sq.Insert(tenantTableName).Columns(d.insertColumns()...).Values(
		tenant.Owner,
		tenant.Name,
		tenant.Description,
		tenant.State,
	).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return 0, err
	}
	result := d.connection.MustExec(ctx, query, args...)
	id, err := result.LastInsertId()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to get last insert id")
		return 0, err
	}

	logger.Info(ctx, "tenant created")
	return id, nil
}

func (d *TenantDAOImpl) UpdateTenantState(ctx context.Context, tenantID int64, state model.TenantState) error {
	logger := log.WithField(ctx, "tenantID", tenantID).WithField(ctx, "state", state)

	query, args, err := sq.Update(tenantTableName).Set("state", state).Where(sq.Eq{"id": tenantID}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return err
	}
	_, err = d.connection.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to exec sql")
		return err
	}

	logger.Warn(ctx, "tenant state updated")
	return nil
}

func init() {
	DefaultTenantDAO = NewTenantDAOImpl()
}
