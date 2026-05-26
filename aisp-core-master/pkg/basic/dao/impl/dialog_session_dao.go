package impl

import (
	"context"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
)

func NewDialogSessionDao() dao.DialogSessionDao {
	return &DialogSessionDaoImpl{
		db: mysql.AispCoreBorm,
	}
}

type DialogSessionDaoImpl struct {
	db *borm.ORM
}

func (d *DialogSessionDaoImpl) CreateSession(ctx context.Context, model *model.DialogSession) (mysql.Result, error) {
	insertResult := d.db.Create(ctx, model)
	if insertResult.Error != nil {
		return mysql.Result{}, insertResult.Error
	}
	return mysql.Result{LastInsertedID: insertResult.LastInsertedID, AffectedRows: insertResult.AffectedRows}, nil
}

func (d *DialogSessionDaoImpl) GetSessionInfo(ctx context.Context, sessionId int64) (*model.DialogSession, error) {
	var result *model.DialogSession
	err := d.db.Where(borm.Eq{"session_id": sessionId}).One(ctx, &result)
	if err != nil {
		return nil, err
	}
	return result, nil
}
