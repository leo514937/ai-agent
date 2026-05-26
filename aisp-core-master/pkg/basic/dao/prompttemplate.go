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

const promptTemplateTableName = "prompt_template"

//go:generate mockery --name PromptTemplateDAO
type PromptTemplateDAO interface {
	CreatePromptTemplate(ctx context.Context, template *model.PromptTemplate) (id int64, err error)
	GetPromptTemplateByID(ctx context.Context, tenantID, id int64) (template *model.PromptTemplate, err error)
}

var DefaultPromptTemplateDAO PromptTemplateDAO

type PromptTemplateDAOImpl struct {
	connection mysql.Connection
}

var _ PromptTemplateDAO = (*PromptTemplateDAOImpl)(nil)

func NewPromptTemplateDAO() PromptTemplateDAO {
	return &PromptTemplateDAOImpl{
		connection: resource.MySQLAISPCore,
	}
}

func (*PromptTemplateDAOImpl) columns() []string {
	// columns of
	// type PromptTemplate struct {
	// 	ID        int64               `json:"id"`
	// 	TenantID  int64               `json:"tenant_id"`
	// 	TaskID    int64               `json:"task_id"`
	// 	State     PromptTemplateState `json:"state"`
	// 	Template  string              `json:"template"`
	// 	CreatedAt time.Time           `json:"created_at"`
	// 	UpdatedAt time.Time           `json:"updated_at"`
	// }
	return []string{
		"id",
		"tenant_id",
		"task_id",
		"state",
		"template",
		"created_at",
		"updated_at",
	}
}

func (*PromptTemplateDAOImpl) insertColumns() []string {
	return []string{
		"id",
		"tenant_id",
		"task_id",
		"state",
		"template",
	}
}

func (d *PromptTemplateDAOImpl) CreatePromptTemplate(ctx context.Context, template *model.PromptTemplate) (id int64, err error) {
	logger := log.WithField(ctx, "template", template)

	qeury, args, err := sq.Insert(promptTemplateTableName).Columns(d.insertColumns()...).Values(
		template.ID,
		template.TenantID,
		template.TaskID,
		template.State,
		template.Template,
	).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return 0, err
	}
	result, err := d.connection.Exec(ctx, qeury, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to exec sql")
		return 0, err
	}
	id, err = result.LastInsertId()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to get last insert id")
		return 0, err
	}

	logger.Info(ctx, "template created")
	return id, nil
}

func (d *PromptTemplateDAOImpl) GetPromptTemplateByID(ctx context.Context, tenantID, id int64) (template *model.PromptTemplate, err error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenant_id": tenantID,
		"id":        id,
	})

	query, args, err := sq.Select(d.columns()...).From(promptTemplateTableName).Where(sq.Eq{"id": id, "tenant_id": tenantID}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return nil, err
	}
	row := d.connection.QueryRow(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to query sql")
		return nil, err
	}

	template = &model.PromptTemplate{}
	err = row.Scan(
		&template.ID,
		&template.TenantID,
		&template.TaskID,
		&template.State,
		&template.Template,
		&template.CreatedAt,
		&template.UpdatedAt,
	)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			logger.Info(ctx, "template not found")
			return nil, nil
		}

		logger.WithError(ctx, err).Error(ctx, "failed to scan row")
		return nil, err
	}
	return template, nil
}

func init() {
	DefaultPromptTemplateDAO = NewPromptTemplateDAO()
}
