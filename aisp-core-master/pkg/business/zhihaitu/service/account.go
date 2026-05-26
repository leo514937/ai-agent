package service

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

var accountDao = dao.DefaultOpenapiAccountDAO
var cryptRpc = impl.DefaultCryptRpc

func Login(ctx context.Context, mobile string, smsCode string) (*model.TableOpenapiAccount, error) {
	encryptMobile, err := cryptRpc.Encrypt(ctx, mobile)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "encrypt mobile error")
	}
	account, err := accountDao.GetByMobile(ctx, encryptMobile, model.NotDeleted)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "get mobile error")
		return nil, err
	}

	return account, nil
}

func GetAccount(ctx context.Context, mobile string) (*model.TableOpenapiAccount, error) {
	encryptMobile, err := cryptRpc.Encrypt(ctx, mobile)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "encrypt mobile error")
	}
	return accountDao.GetByMobile(ctx, encryptMobile, model.NotDeleted)
}
