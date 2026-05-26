package arena

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	domainModel "git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type Service interface {
	UpdateArenaState(ctx context.Context, arenaID int64, state domainModel.ArenaState) error
}

type Impl struct {
	arenaDAO dao.ArenaDAO
}

var (
	_              Service = (*Impl)(nil)
	DefaultService Service = NewService()
)

func NewService() Service {
	return &Impl{
		arenaDAO: dao.DefaultArenaDAO,
	}
}

func (i *Impl) UpdateArenaState(ctx context.Context, arenaID int64, state domainModel.ArenaState) error {
	return i.arenaDAO.UpdateArenaState(ctx, arenaID, state)
}
