package dao

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
	"github.com/samber/lo"
)

const dialogueTableName = "dialogue"

//go:generate mockery --name DialogueDAO
type DialogueDAO interface {
	CreateDialogue(ctx context.Context, dialogue *model.Dialogue) (int64, error)
	GetDialogueByID(ctx context.Context, tenantID, dialogueID int64) (*model.Dialogue, error)
	ListDialogueByConversationID(ctx context.Context, tenantID, conversationID int64, offset, limit int64) ([]*model.Dialogue, error)
	SetChatResult(ctx context.Context, tenantID, dialogueID int64, chatResult *model.DialogueResult) error
}

var DefaultDialogueDAO DialogueDAO

type DialogueDAOImpl struct {
	connection mysql.Connection
}

func NewDialogueDAO() *DialogueDAOImpl {
	return &DialogueDAOImpl{
		connection: resource.MySQLAISPCore,
	}
}

func (*DialogueDAOImpl) columns() []string {
	// columns of
	// type Dialogue struct {
	// 	ID               int64              `json:"id"`
	// 	TenantID         int64              `json:"tenant_id"`
	// 	TaskID           int64              `json:"task_id"`
	// 	ConversationID   int64              `json:"conversation_id"`
	// 	UserID           string 		    `json:"user_id"`
	// 	UserMessage      string             `json:"user_message"`
	// 	AIMessage        string             `json:"ai_message"`
	// 	Context          *Context           `json:"context"`
	// 	InputTokenCount  int64              `json:"input_token_count"`
	// 	OutputTokenCount int64              `json:"output_token_count"`
	// 	State            DialogueState      `json:"state"`
	// 	AuditState       DialogueAuditState `json:"audit_state"`
	// 	AuditReason      string             `json:"audit_reason"`
	// 	CreatedAt        time.Time          `json:"created_at"`
	// 	UpdatedAt        time.Time          `json:"updated_at"`
	// }
	return []string{
		"id",
		"tenant_id",
		"task_id",
		"conversation_id",
		"user_id",
		"user_message",
		"ai_message",
		"custom",
		"context_",
		"input_token_count",
		"output_token_count",
		"state",
		"audit_state",
		"audit_reason",
		"created_at",
		"updated_at",
	}
}

func (*DialogueDAOImpl) insertColumns() []string {
	return []string{
		"id",
		"tenant_id",
		"task_id",
		"conversation_id",
		"user_id",
		"user_message",
		"ai_message",
		"custom",
		"context_",
		"input_token_count",
		"output_token_count",
		"state",
		"audit_state",
		"audit_reason",
	}
}

func (d *DialogueDAOImpl) CreateDialogue(ctx context.Context, dialogue *model.Dialogue) (int64, error) {
	logger := log.WithField(ctx, "dialogue", dialogue)

	query, args, err := sq.Insert(dialogueTableName).Columns(d.insertColumns()...).Values(
		dialogue.ID,
		dialogue.TenantID,
		dialogue.TaskID,
		dialogue.ConversationID,
		dialogue.UserID,
		dialogue.UserMessage,
		dialogue.AIMessage,
		lo.Must(json.Marshal(dialogue.Custom)),
		lo.Must(json.Marshal(dialogue.Context)),
		dialogue.InputTokenCount,
		dialogue.OutputTokenCount,
		dialogue.State,
		dialogue.AuditState,
		dialogue.AuditReason,
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

	logger.Info(ctx, "create dialogue success")
	return id, nil
}

func (d *DialogueDAOImpl) GetDialogueByID(ctx context.Context, tenantID, dialogueID int64) (*model.Dialogue, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenant_id":   tenantID,
		"dialogue_id": dialogueID,
	})

	query, args, err := sq.Select(d.columns()...).From(dialogueTableName).Where(sq.Eq{"id": dialogueID, "tenant_id": tenantID}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return nil, err
	}

	row := d.connection.QueryRow(ctx, query, args...)
	var (
		dialogue model.Dialogue
		custom   string
		context  string
	)
	err = row.Scan(
		&dialogue.ID,
		&dialogue.TenantID,
		&dialogue.TaskID,
		&dialogue.ConversationID,
		&dialogue.UserID,
		&dialogue.UserMessage,
		&dialogue.AIMessage,
		&custom,
		&context,
		&dialogue.InputTokenCount,
		&dialogue.OutputTokenCount,
		&dialogue.State,
		&dialogue.AuditState,
		&dialogue.AuditReason,
		&dialogue.CreatedAt,
		&dialogue.UpdatedAt,
	)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			logger.WithError(ctx, err).Error(ctx, "dialogue not found")
			return nil, nil
		}
		logger.WithError(ctx, err).Error(ctx, "failed to scan row")
		return nil, err
	}
	if context != "" {
		dialogue.Context = nil
		err := util.JSONUnmarshal([]byte(context), &dialogue.Context)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to unmarshal context")
			return nil, err
		}
	}
	if custom != "" {
		err := util.JSONUnmarshal([]byte(custom), &dialogue.Custom)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to unmarshal custom")
			return nil, err
		}
	}
	return &dialogue, nil
}

func (d *DialogueDAOImpl) ListDialogueByConversationID(ctx context.Context, tenantID, conversationID int64, offset, limit int64) ([]*model.Dialogue, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenant_id":       tenantID,
		"conversation_id": conversationID,
		"offset":          offset,
		"limit":           limit,
	})

	query, args, err := sq.Select(d.columns()...).From(dialogueTableName).Where(sq.Eq{"conversation_id": conversationID, "tenant_id": tenantID}).OrderBy("created_at DESC").Limit(uint64(limit)).Offset(uint64(offset)).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return nil, err
	}

	rows, err := d.connection.Query(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to query sql")
		return nil, err
	}
	defer rows.Close()

	var dialogues []*model.Dialogue
	for rows.Next() {
		var (
			dialogue model.Dialogue
			context  string
			custom   string
		)
		err = rows.Scan(
			&dialogue.ID,
			&dialogue.TenantID,
			&dialogue.TaskID,
			&dialogue.ConversationID,
			&dialogue.UserID,
			&dialogue.UserMessage,
			&dialogue.AIMessage,
			&custom,
			&context,
			&dialogue.InputTokenCount,
			&dialogue.OutputTokenCount,
			&dialogue.State,
			&dialogue.AuditState,
			&dialogue.AuditReason,
			&dialogue.CreatedAt,
			&dialogue.UpdatedAt,
		)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to scan row")
			return nil, err
		}
		if context != "" {
			err := util.JSONUnmarshal([]byte(context), &dialogue.Context)
			if err != nil {
				logger.WithError(ctx, err).Error(ctx, "failed to unmarshal context")
				return nil, err
			}
		}
		if custom != "" {
			err := util.JSONUnmarshal([]byte(custom), &dialogue.Custom)
			if err != nil {
				logger.WithError(ctx, err).Error(ctx, "failed to unmarshal custom")
				return nil, err
			}
		}
		dialogues = append(dialogues, &dialogue)
	}
	return dialogues, nil
}

func (d *DialogueDAOImpl) SetChatResult(ctx context.Context, tenantID, dialogueID int64, chatResult *model.DialogueResult) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenant_id":   tenantID,
		"dialogue_id": dialogueID,
		"chat_result": chatResult,
	})

	updates := map[string]any{}
	if chatResult.AIMessage != nil {
		updates["ai_message"] = *chatResult.AIMessage
	}
	if chatResult.Context != nil {
		updates["context_"] = *chatResult.Context
	}
	if chatResult.State != nil {
		updates["state"] = *chatResult.State
	}
	if chatResult.AuditState != nil {
		updates["audit_state"] = *chatResult.AuditState
	}
	if chatResult.AuditReason != nil {
		updates["audit_reason"] = *chatResult.AuditReason
	}
	if chatResult.InputTokenCount != nil {
		updates["input_token_count"] = *chatResult.InputTokenCount
	}
	if chatResult.OutputTokenCount != nil {
		updates["output_token_count"] = *chatResult.OutputTokenCount
	}
	if len(updates) == 0 {
		logger.Info(ctx, "no chat result need to update")
		return nil
	}
	query, args, err := sq.Update(dialogueTableName).SetMap(updates).Where(sq.Eq{"id": dialogueID, "tenant_id": tenantID}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return err
	}

	_, err = d.connection.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to exec sql")
		return err
	}

	logger.Info(ctx, "set chat result success")
	return nil
}

func init() {
	DefaultDialogueDAO = NewDialogueDAO()
}
