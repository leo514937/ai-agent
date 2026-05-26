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

const taskTableName = "task"

//go:generate mockery --name TaskDAO
type TaskDAO interface {
	GetTaskByID(ctx context.Context, tenantID, taskID int64) (*model.Task, error)
	CreateTask(ctx context.Context, task *model.Task) (int64, error)
	UpdateTaskState(ctx context.Context, tenantID, taskID int64, state model.TaskState) error
}

var _ TaskDAO = (*TaskDAOImpl)(nil)

var DefaultTaskDAO TaskDAO

type TaskDAOImpl struct {
	connection mysql.Connection
}

func NewTaskDAO() *TaskDAOImpl {
	return &TaskDAOImpl{
		connection: resource.MySQLAISPCore,
	}
}

func (*TaskDAOImpl) columns() []string {
	// columns of
	// type Task struct {
	// 	ID                  int64             `json:"id"`
	// 	TenantID            int64             `json:"tenant_id"`
	// 	Name                string            `json:"name"`
	// 	Owner               string            `json:"owner"`
	// 	Description         string            `json:"description"`
	// 	AIProfile           string            `json:"ai_profile"`
	// 	PromptTemplateID    int64             `json:"prompt_template_id"`
	// 	ModelEngineTaskName string            `json:"model_engine_task_name"`
	// 	State               TaskState         `json:"state"`
	// 	AuditMode           AuditMode         `json:"audit_mode"`
	// 	ConversationModel   ConversationModel `json:"conversation_model"`
	// 	RateLimit           int64             `json:"rate_limit"`
	// 	CreatedAt           time.Time         `json:"created_at"`
	// 	UpdatedAt           time.Time         `json:"updated_at"`
	// }
	return []string{
		"id",
		"tenant_id",
		"name_",
		"owner_",
		"description_",
		"ai_profile",
		"prompt_template_id",
		"model_engine_task_name",
		"state",
		"audit_mode",
		"conversation_model",
		"rate_limit",
		"created_at",
		"updated_at",
	}
}

func (*TaskDAOImpl) insertColumns() []string {
	return []string{
		"id",
		"tenant_id",
		"name_",
		"owner_",
		"description_",
		"ai_profile",
		"prompt_template_id",
		"model_engine_task_name",
		"state",
		"audit_mode",
		"conversation_model",
		"rate_limit",
	}
}

func (d *TaskDAOImpl) GetTaskByID(ctx context.Context, tenantID, taskID int64) (*model.Task, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenant_id": tenantID,
		"task_id":   taskID,
	})

	query, args, err := sq.Select(d.columns()...).From(taskTableName).Where(sq.Eq{"id": taskID, "tenant_id": tenantID}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return nil, err
	}
	row := d.connection.QueryRow(ctx, query, args...)
	var task model.Task
	err = row.Scan(
		&task.ID,
		&task.TenantID,
		&task.Name,
		&task.Owner,
		&task.Description,
		&task.AIProfile,
		&task.PromptTemplateID,
		&task.ModelEngineTaskName,
		&task.State,
		&task.AuditMode,
		&task.ConversationModel,
		&task.RateLimit,
		&task.CreatedAt,
		&task.UpdatedAt,
	)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			logger.Warn(ctx, "task not found")
			return nil, nil
		}

		logger.WithError(ctx, err).Error(ctx, "failed to scan row")
		return nil, err
	}
	return &task, nil
}

func (d *TaskDAOImpl) CreateTask(ctx context.Context, task *model.Task) (int64, error) {
	logger := log.WithField(ctx, "task", task)

	query, args, err := sq.Insert(taskTableName).Columns(d.insertColumns()...).Values(
		task.ID,
		task.TenantID,
		task.Name,
		task.Owner,
		task.Description,
		task.AIProfile,
		task.PromptTemplateID,
		task.ModelEngineTaskName,
		task.State,
		task.AuditMode,
		task.ConversationModel,
		task.RateLimit,
	).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return 0, err
	}
	result, err := d.connection.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to exec sql")
		return 0, err
	}
	id, err := result.LastInsertId()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to get last insert id")
		return 0, err
	}

	logger.Info(ctx, "task created")
	return id, nil
}

func (d *TaskDAOImpl) UpdateTaskState(ctx context.Context, tenantID, taskID int64, state model.TaskState) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenant_id": tenantID,
		"task_id":   taskID,
		"state":     state,
	})

	query, args, err := sq.Update(taskTableName).Set("state", state).Where(sq.Eq{"id": taskID, "tenant_id": tenantID}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return err
	}
	_, err = d.connection.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to exec sql")
		return err
	}

	logger.Info(ctx, "task state updated")
	return nil
}

func init() {
	DefaultTaskDAO = NewTaskDAO()
}
