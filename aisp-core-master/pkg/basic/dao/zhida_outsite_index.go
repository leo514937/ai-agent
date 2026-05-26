package dao

import (
	"context"
)

type ZhidaOutSiteIndexDao interface {
	GetItemUpdateLock(ctx context.Context, url string, content string) bool
}
