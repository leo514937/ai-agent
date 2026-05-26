package rpc

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-user_core/user_core_thrift"
)

type UserCoreService interface {
	BatchGetUserByIds(ctx context.Context, ids []int64, withFields []string) (map[int64]*user_core_thrift.User, error)
	BatchGetUserByHashIds(ctx context.Context, hashIds []string, withFields []string) (map[string]*user_core_thrift.User, error)
}
