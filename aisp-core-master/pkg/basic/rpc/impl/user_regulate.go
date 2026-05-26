package impl

import (
	"context"
	"errors"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-user_regulate_core/user_regulate_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

var DefaultUserRegulateService rpc.UserRegulateService

func init() {
	DefaultUserRegulateService = NewUserRegulateService()
}

type UserRegulateServiceImpl struct {
	client *user_regulate_core_thrift.UserRegulateServiceClient
}

func (u *UserRegulateServiceImpl) CanLogin(ctx context.Context, memberId int64) (bool, error) {
	status, err := u.QueryUserStatus(ctx, memberId, "zhihaitu_account_login")
	if err != nil {
		return false, err
	}

	return status == rpc.UserRegulateStatusNormal, nil
}

func (u *UserRegulateServiceImpl) CanSubmit(ctx context.Context, memberId int64) (bool, error) {
	status, err := u.QueryUserStatus(ctx, memberId, "zhihaitu_create_question")
	if err != nil {
		return false, err
	}

	return status == rpc.UserRegulateStatusNormal, nil
}

func (u *UserRegulateServiceImpl) QueryUserStatus(ctx context.Context, memberId int64, sceneCode string) (rpc.UserRegulateStatus, error) {
	var status = rpc.UserRegulateStatusUnknown

	runFunc := func(ctx context.Context) (err error) {
		param := &user_regulate_core_thrift.BatchRegulateParam{
			ScenesCode: sceneCode,
			UserIds:    []int64{memberId},
		}
		logger := log.WithField(ctx, "memberId", memberId)
		response, err := u.client.BatchRegulate(ctx, param)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "BatchRegulate error")
			status = rpc.UserRegulateStatusUnknown
			return err
		}

		if len(response.GetResponse()) != 1 {
			err = errors.New("接口返回结果错误")
			logger.WithError(ctx, err).Error(ctx, "BatchRegulate error")
			status = rpc.UserRegulateStatusUnknown
			return err
		}

		logger.Info(ctx, "BatchRegulate response: ", response.GetResponse()[0].ActionInfo.CanDo)

		if response.GetResponse()[0].ActionInfo.CanDo {
			status = rpc.UserRegulateStatusNormal
		} else {
			status = rpc.UserRegulateStatusError
		}
		return nil
	}

	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return status, nil
}

func NewUserRegulateService() *UserRegulateServiceImpl {
	return &UserRegulateServiceImpl{
		client: user_regulate_core_thrift.NewUserRegulateServiceClient(tzone.NewClient(
			"UserRegulateService",
			tzone.TargetName("user-regulate-core-rpc"),
			tzone.Timeout(1*time.Second))),
	}
}
