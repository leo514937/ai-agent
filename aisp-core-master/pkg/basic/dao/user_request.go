package dao

import (
	"context"
)

type UserRequestDao interface {
	GetUserRequestFrequencyLock(ctx context.Context, memberId int64, sceneType string, ttlSeconds int) bool
}
