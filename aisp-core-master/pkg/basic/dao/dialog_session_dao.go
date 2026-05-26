package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type DialogSessionDao interface {
	// CreateSession 创建Session
	CreateSession(ctx context.Context, model *model.DialogSession) (mysql.Result, error)
	GetSessionInfo(ctx context.Context, sessionId int64) (*model.DialogSession, error)
}
