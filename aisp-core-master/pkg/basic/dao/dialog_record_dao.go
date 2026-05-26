package dao

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

//go:generate mockery --name WordMapperDAO
type DialogRecordDAO interface {

	// SaveDialogs 保存全部会话
	SaveDialogs(ctx context.Context, dtos []*model.DialogRecord) (mysql.Result, error)

	// SaveOrUpdateDialog 保存/更新 会话
	SaveOrUpdateDialog(ctx context.Context, dto *model.DialogRecord) (mysql.Result, error)

	// GetDialogListBySessionId 根据SessionId获取会话列表
	GetDialogListBySessionId(ctx context.Context, sessionId int64, limit uint64) ([]*model.DialogRecord, error)

	// GetDialogBySessionIdAndMessageId 根据SessionId 和 消息Id  获取会话
	GetDialogBySessionIdAndMessageId(ctx context.Context, sessionId int64, messageId string) (*model.DialogRecord, error)

	// GetDialogByGroupIds 根据SessionId 和 GroupIds  获取会话
	GetDialogByGroupIds(ctx context.Context, sessionId int64, messageId []string) ([]*model.DialogRecord, error)

	GetDialogsBySessionIdAndMaxCreateTime(ctx context.Context, sessionId int64, createAt time.Time) ([]*model.DialogRecord, error)
}
