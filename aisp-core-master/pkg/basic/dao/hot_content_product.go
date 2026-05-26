package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type HotContentProductDAO interface {
	FindByFilterParams(ctx context.Context, filterParams *model.HotContentFilterParams) ([]*model.HotContentProducts, int64, string, error)
	FindTrendByFilterParams(ctx context.Context, filterParams *model.HotContentFilterParams) ([]*model.HotContentProductScore, error)
	DeleteByPDate(ctx context.Context, pDate string) error
}
