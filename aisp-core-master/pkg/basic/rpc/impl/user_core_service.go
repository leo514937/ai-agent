package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-user_core/user_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
)

type UserCoreServiceImpl struct {
	client *user_core_thrift.UserServiceClient
}

var DefaultUserCoreServiceImpl rpc.UserCoreService

func init() {
	DefaultUserCoreServiceImpl = NewUserCoreServiceImpl()
}

func NewUserCoreServiceImpl() *UserCoreServiceImpl {
	return &UserCoreServiceImpl{
		client: user_core_thrift.NewUserServiceClient(
			tzone.NewClient(
				"UserService",
				tzone.TargetName("user-core-rpc"),
				tzone.Timeout(300*time.Millisecond),
			)),
	}
}

func (u *UserCoreServiceImpl) BatchGetUserByIds(ctx context.Context, ids []int64, withFields []string) (map[int64]*user_core_thrift.User, error) {
	ret := make(map[int64]*user_core_thrift.User)
	param := &user_core_thrift.BatchGetUserParam{
		Ids:        &ids,
		WithFields: &withFields,
	}
	users, err := u.client.BatchGetUser(ctx, param)
	if err != nil {
		return nil, err
	}
	for _, user := range users {
		if user != nil && user.GetMeta() != nil {
			if _, ok := ret[user.GetMeta().GetID()]; !ok {
				ret[user.GetMeta().GetID()] = user
			}
		}
	}
	return ret, nil
}

func (u *UserCoreServiceImpl) BatchGetUserByHashIds(ctx context.Context, hashIds []string, withFields []string) (map[string]*user_core_thrift.User, error) {
	ret := make(map[string]*user_core_thrift.User)
	param := &user_core_thrift.BatchGetUserParam{
		HashIds:    &hashIds,
		WithFields: &withFields,
	}
	users, err := u.client.BatchGetUser(ctx, param)
	if err != nil {
		return nil, err
	}
	for _, user := range users {
		if user != nil && user.GetMeta() != nil {
			if _, ok := ret[user.GetMeta().GetHashID()]; !ok {
				ret[user.GetMeta().GetHashID()] = user
			}
		}
	}
	return ret, nil
}
