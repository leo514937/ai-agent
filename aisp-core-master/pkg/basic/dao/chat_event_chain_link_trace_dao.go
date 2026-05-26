package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type ChatEventChainLinkTraceDao interface {
	SaveTrace(ctx context.Context, model *model.ChatEventChainLinkTrace) (mysql.Result, error)
	GetTrace(ctx context.Context, traceId string) (*model.ChatEventChainLinkTrace, error)
	ClearExpireCache(ctx context.Context)
}
