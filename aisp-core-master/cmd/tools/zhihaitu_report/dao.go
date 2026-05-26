package main

import (
	"context"
	"database/sql"
	"fmt"

	"git.in.zhihu.com/go/base/telemetry/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	"github.com/Masterminds/squirrel"
)

type LucaDaoImpl struct {
	LucaPool mysql.Connection
}

func NewLucaDaoImpl() *LucaDaoImpl {
	return &LucaDaoImpl{
		LucaPool: mysql.NewConnection("luca_backend"),
	}
}

func (c *LucaDaoImpl) QueryALlConvMessage(ctx context.Context) ([]*model.TableBmbConvMessage, error) {
	var err error
	var rows *sql.Rows
	var strSql string
	var args []interface{}

	cond := squirrel.Eq{}

	// sql exec

	var dbModel model.TableBmbConvMessage
	tbName := dbModel.TableName()

	strSql, args, err = squirrel.Select(dbModel.GetColumnNames()).From(tbName).Where(cond).OrderBy("create_time").ToSql()

	if err != nil {
		errMsg := fmt.Sprintf("[err]QueryALlConvMessage Build sql failed, err=%+v", err)
		log.Errorf(ctx, errMsg)
		return nil, err
	}

	rows, err = c.LucaPool.Query(ctx, strSql, args...)

	if err != nil {
		errMsg := fmt.Sprintf("[err]sql exec failed reason=[%s] sql=[%s]", err.Error(), strSql)
		log.Error(ctx, errMsg)
		return nil, err
	}
	defer rows.Close()

	itemList := make([]*model.TableBmbConvMessage, 0)

	for rows.Next() {
		item := new(model.TableBmbConvMessage)
		err = rows.Scan(
			&item.ID,
			&item.ConvID,
			&item.MsgID,
			&item.AccountID,
			&item.Role,
			&item.Content,
			&item.Rating,
			&item.FeedbackMsg,
			&item.IsDeleted,
			&item.CreateTime,
			&item.UpdateTime,
			&item.FeedbackAction,
			&item.ParentMsgID,
			&item.CostTimeMillis,
			&item.ImageID,
			&item.MsgType,
			&item.State,
			&item.StopEnum,
			&item.AppID,
			&item.StopPosition,
		)
		if err != nil {
			errMsg := fmt.Sprintf("[err]QueryALlConvMessage Get target records from mysql failed, err=%+v, sql=%s", err, strSql)
			log.Errorf(ctx, errMsg)
			return nil, err
		}

		itemList = append(itemList, item)
	}

	return itemList, nil
}
