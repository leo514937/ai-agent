package rpc

import (
	"context"
)

type UserRegulateStatus int

const (
	UserRegulateStatusUnknown UserRegulateStatus = 0
	UserRegulateStatusNormal  UserRegulateStatus = 1 //正常
	UserRegulateStatusError   UserRegulateStatus = 2 //无法登录
)

type UserRegulateService interface {
	// QueryUserStatus 查询用户状态是否被监管管控
	QueryUserStatus(ctx context.Context, memberId int64, sceneCode string) (UserRegulateStatus, error)
	CanLogin(ctx context.Context, memberId int64) (bool, error)
	CanSubmit(ctx context.Context, memberId int64) (bool, error)
}
