package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/redis"
	"github.com/pkg/errors"
	"github.com/vmihailenco/msgpack/v5"
)

type AsyncHTTPConnDAO interface {
	GetAsyncHTTPConn(ctx context.Context, id string) (*model.AsyncHTTPConn, error)
	SetAsyncHTTPConn(ctx context.Context, asyncConn *model.AsyncHTTPConn) error
}

var (
	DefaultAsyncHTTPConnDAO AsyncHTTPConnDAO = NewAsyncConnDAOImpl()
	_                       AsyncHTTPConnDAO = (*AsyncConnDAOImpl)(nil)
)

type AsyncConnDAOImpl struct {
	cli redis.Client
}

func (d *AsyncConnDAOImpl) GetAsyncHTTPConn(ctx context.Context, id string) (*model.AsyncHTTPConn, error) {
	logger := log.WithFields(ctx, map[string]any{
		"func": "core.dao.AsyncConnDAOImpl.GetAsyncHTTPConn",
		"id":   id,
	})
	raw, err := d.cli.Get(ctx, id).Result()
	if errors.Is(err, redis.ErrNil) {
		return nil, nil
	}
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to get async http conn")
		return nil, err
	}
	asyncConn := &model.AsyncHTTPConn{}
	if err := msgpack.Unmarshal([]byte(raw), asyncConn); err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to unmarshal async http conn")
		return nil, err
	}
	return asyncConn, nil
}

func (d *AsyncConnDAOImpl) SetAsyncHTTPConn(ctx context.Context, asyncConn *model.AsyncHTTPConn) error {
	logger := log.WithFields(ctx, map[string]any{
		"func":      "core.dao.AsyncConnDAOImpl.SetAsyncHTTPConn",
		"asyncConn": asyncConn,
	})
	raw, err := msgpack.Marshal(asyncConn)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to marshal async http conn")
		return err
	}
	if err := d.cli.Set(ctx, asyncConn.ID, raw, asyncConn.TTL).Err(); err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to set async http conn")
		return err
	}
	logger.Info(ctx, "set async http conn")
	return nil
}

func NewAsyncConnDAOImpl() *AsyncConnDAOImpl {
	return &AsyncConnDAOImpl{
		cli: resource.DashboardAsyncRequest,
	}
}
