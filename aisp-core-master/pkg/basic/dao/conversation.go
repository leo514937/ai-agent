package dao

import (
	"context"
	"database/sql"
	"encoding/json"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
	"github.com/samber/lo"
)

const conversationTableName = "conversation"

//go:generate mockery --name ConversationDAO
type ConversationDAO interface {
	CreateConversation(ctx context.Context, conversation *model.Conversation) (int64, error)
	GetConversationByID(ctx context.Context, tenantID, conversationID int64) (*model.Conversation, error)
	UpdateConversationState(ctx context.Context, tenantID, conversationID int64, state model.ConversationState) error
}

var DefaultConversationDAO ConversationDAO

type ConversationDAOImpl struct {
	connection mysql.Connection
}

var _ ConversationDAO = (*ConversationDAOImpl)(nil)

func NewConversationDAOImpl() *ConversationDAOImpl {
	return &ConversationDAOImpl{
		connection: resource.MySQLAISPCore,
	}
}

func (*ConversationDAOImpl) columns() []string {
	// columns of
	// type Conversation struct {
	// 	ID        int64             `json:"id"`
	// 	TenantID  int64             `json:"tenant_id"`
	// 	TaskID    int64             `json:"task_id"`
	// 	CreatorID string            `json:"creator_id"`
	// 	State     ConversationState `json:"state"`
	// 	System    map[string]any    `json:"system"`
	// 	CreatedAt time.Time         `json:"created_at"`
	// 	UpdatedAt time.Time         `json:"updated_at"`
	// }
	return []string{
		"id",
		"tenant_id",
		"task_id",
		"creator_id",
		"state",
		"system_",
		"created_at",
		"updated_at",
	}
}

func (*ConversationDAOImpl) insertColumns() []string {
	return []string{
		"id",
		"tenant_id",
		"task_id",
		"creator_id",
		"state",
		"system_",
	}
}

func (d *ConversationDAOImpl) CreateConversation(ctx context.Context, conversation *model.Conversation) (int64, error) {
	logger := log.WithField(ctx, "conversation", conversation)

	query, args, err := sq.Insert(conversationTableName).Columns(d.insertColumns()...).Values(
		conversation.ID,
		conversation.TenantID,
		conversation.TaskID,
		conversation.CreatorID,
		conversation.State,
		lo.Must(json.Marshal(conversation.System)),
	).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return 0, err
	}
	_, err = d.connection.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to exec sql")
		return 0, err
	}

	logger.Info(ctx, "conversation created")
	return conversation.ID, nil
}

func (d *ConversationDAOImpl) GetConversationByID(ctx context.Context, tenantID, conversationID int64) (*model.Conversation, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenant_id":       tenantID,
		"conversation_id": conversationID,
	})

	query, args, err := sq.Select(d.columns()...).From(conversationTableName).Where(sq.Eq{"id": conversationID}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return nil, err
	}
	row := d.connection.QueryRow(ctx, query, args...)
	conversation := &model.Conversation{}
	var system string
	err = row.Scan(
		&conversation.ID,
		&conversation.TenantID,
		&conversation.TaskID,
		&conversation.CreatorID,
		&conversation.State,
		&system,
		&conversation.CreatedAt,
		&conversation.UpdatedAt,
	)
	if err != nil {
		if err == sql.ErrNoRows {
			logger.Warn(ctx, "conversation not found")
			return nil, nil
		}
		logger.WithError(ctx, err).Error(ctx, "failed to scan row")
		return nil, err
	}
	if system != "" {
		err := util.JSONUnmarshal([]byte(system), &conversation.System)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "failed to unmarshal system")
			return nil, err
		}
	}
	return conversation, nil
}

func (d *ConversationDAOImpl) UpdateConversationState(ctx context.Context, tenantID, conversationID int64, state model.ConversationState) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"tenant_id":       tenantID,
		"conversation_id": conversationID,
		"state":           state,
	})

	query, args, err := sq.Update(conversationTableName).Set("state", state).Where(sq.Eq{"id": conversationID}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql")
		return err
	}
	_, err = d.connection.Exec(ctx, query, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to exec sql")
		return err
	}

	logger.Info(ctx, "conversation state updated")
	return nil
}

func init() {
	DefaultConversationDAO = NewConversationDAOImpl()
}
