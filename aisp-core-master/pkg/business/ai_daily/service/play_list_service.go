package service

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/dao"
)

type PlaylistService interface {
	GetPlaylistHistoryByUserID(ctx context.Context, userID int64) ([]string, error)
}

type PlaylistServiceImpl struct {
}

func newPlaylistServiceImpl() PlaylistService {
	return &PlaylistServiceImpl{}
}

var DefaultPlaylistService PlaylistService

func init() {
	DefaultPlaylistService = newPlaylistServiceImpl()
}

func (p *PlaylistServiceImpl) GetPlaylistHistoryByUserID(ctx context.Context, userID int64) ([]string, error) {
	return dao.DefaultDailySnapshotDAO.GetDailySnapshotDateByUserIDOrderByDate(ctx, userID)
}
