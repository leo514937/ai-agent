package dao

import "context"

type ZhiDaSkuDao interface {
	GetSkuLinkCardIds(ctx context.Context, aliasArray []string) map[string]int64
}
