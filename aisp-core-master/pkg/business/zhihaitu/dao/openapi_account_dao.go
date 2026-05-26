package dao

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

type OpenapiAccountDAO interface {
	GetAccountInfoByID(ctx context.Context, id int64) (*model.TableOpenapiAccount, *macro.ServiceError)
	GetByStatus(ctx context.Context, accountId int64, deleteStatus int, status int) (*model.TableOpenapiAccount, error)
	GetByMobile(ctx context.Context, encryptMobile string, deleteStatus int) (*model.TableOpenapiAccount, error)
	GetByMemberId(ctx context.Context, memberId int64) (*model.TableOpenapiAccount, error)
	ListAll(ctx context.Context) ([]*model.TableOpenapiAccount, error)
	UpdateEncryptMobile(ctx context.Context, account *model.TableOpenapiAccount) error
}

type OpenapiAccountDAOImpl struct {
}

func newOpenapiAccountDAO() OpenapiAccountDAO {
	return &OpenapiAccountDAOImpl{}
}

var DefaultOpenapiAccountDAO OpenapiAccountDAO

func init() {
	DefaultOpenapiAccountDAO = newOpenapiAccountDAO()
}

func (o *OpenapiAccountDAOImpl) GetAccountInfoByID(ctx context.Context, id int64) (*model.TableOpenapiAccount, *macro.ServiceError) {
	db := mysql.LucaBorm
	var account *model.TableOpenapiAccount
	err := db.FindByPK(ctx, &account, id)
	if err != nil {
		log.WithField(ctx, "id", id).WithError(ctx, err).Errorf(ctx, "[GetAccountInfoByID] failed.")
		if err == borm.ErrRecordNotFound {
			return nil, macro.NewServiceError(macro.SERVICE_CODE_USER_NOT_FOUND, err)
		}
		return nil, macro.NewServiceError(macro.SERVICE_CODE_DB_ERR, err)
	}
	return account, nil
}

func (o *OpenapiAccountDAOImpl) GetByStatus(ctx context.Context, accountId int64, deleteStatus int, status int) (*model.TableOpenapiAccount, error) {
	db := mysql.LucaBorm

	var account *model.TableOpenapiAccount
	err := db.Where(borm.Eq{"id": accountId}).Where(borm.Eq{"is_deleted": deleteStatus}).Where(borm.Eq{"status": status}).One(ctx, &account)
	if err != nil {
		return nil, err
	}

	return account, nil
}

func (o *OpenapiAccountDAOImpl) GetByMobile(ctx context.Context, encryptMobile string, deleteStatus int) (*model.TableOpenapiAccount, error) {
	db := mysql.LucaBorm

	var account *model.TableOpenapiAccount
	err := db.Where(borm.Eq{"encrypt_mobile": encryptMobile}).Where(borm.Eq{"is_deleted": deleteStatus}).One(ctx, &account)
	if err != nil {
		return nil, err
	}

	return account, nil
}

func (o *OpenapiAccountDAOImpl) GetByMemberId(ctx context.Context, memberId int64) (*model.TableOpenapiAccount, error) {
	db := mysql.LucaBorm

	var account *model.TableOpenapiAccount
	err := db.Where(borm.Eq{"member_id": memberId}).One(ctx, &account)
	if err != nil {
		return nil, err
	}

	return account, nil
}

func (o *OpenapiAccountDAOImpl) ListAll(ctx context.Context) ([]*model.TableOpenapiAccount, error) {
	db := mysql.LucaBorm

	var accounts []*model.TableOpenapiAccount
	err := db.All(ctx, &accounts)
	if err != nil {
		return nil, err
	}

	return accounts, nil
}

func (o *OpenapiAccountDAOImpl) UpdateEncryptMobile(ctx context.Context, account *model.TableOpenapiAccount) error {
	db := mysql.LucaBorm

	params := map[string]interface{}{}
	if account.EncryptMobile != "" {
		params["encrypt_mobile"] = account.EncryptMobile
	}

	updateQueryResult := db.Model(account).Updates(ctx, params)

	return updateQueryResult.Error
}
