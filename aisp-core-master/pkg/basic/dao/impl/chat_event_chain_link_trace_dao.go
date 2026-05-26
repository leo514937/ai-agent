package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
)

func NewChatEventChainLinkTraceDao() dao.ChatEventChainLinkTraceDao {
	return &ChatEventChainLinkTraceDaoImpl{
		db: mysql.AispInternalBorm,
	}
}

type ChatEventChainLinkTraceDaoImpl struct {
	db *borm.ORM
}

func (d *ChatEventChainLinkTraceDaoImpl) SaveTrace(ctx context.Context, model *model.ChatEventChainLinkTrace) (mysql.Result, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ChatEventChainLinkTraceDao.SaveTrace",
	})
	insertResult := d.db.Create(ctx, model)
	if insertResult.Error != nil {
		logger.WithError(ctx, insertResult.Error).Errorf(ctx, "save ")
		return mysql.Result{}, insertResult.Error
	}
	return mysql.Result{LastInsertedID: insertResult.LastInsertedID, AffectedRows: insertResult.AffectedRows}, nil
}

func (d *ChatEventChainLinkTraceDaoImpl) GetTrace(ctx context.Context, traceId string) (*model.ChatEventChainLinkTrace, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ChatEventChainLinkTraceDao.GetTrace",
	})
	var result *model.ChatEventChainLinkTrace
	err := d.db.Where(borm.Eq{"trace_id": traceId}).One(ctx, &result)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "get trace %s error", traceId)
		return nil, err
	}
	return result, nil
}

func (d *ChatEventChainLinkTraceDaoImpl) ClearExpireCache(ctx context.Context) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "ChatEventChainLinkTraceDao.ClearExpireCache",
	})

	logger.Infof(ctx, "do clear expire cache.")
	limit := 500
	traceList := make([]*model.ChatEventChainLinkTrace, 0)
	ormErr := d.db.Where(borm.LT{
		"created_at": time.Now().Add(-8 * 24 * time.Hour).Format("2006-01-02 15:04:05"),
	}).OrderBy("created_at").Limit(limit+1).All(ctx, &traceList)
	if ormErr != nil {
		logger.WithError(ctx, ormErr).Errorf(ctx, "tidb check data error.")
		return
	}

	if len(traceList) > 0 {
		delError := d.db.Delete(ctx, traceList[0:zrecUtil.Min(limit, len(traceList))])
		if delError != nil {
			logger.WithError(ctx, delError).Errorf(ctx, "tidb clear expire trace error. => %s", delError.Error())
			return
		}
		// 存在可删除内容 则继续删除
		if len(traceList) > limit {
			// 休眠0.1秒
			time.Sleep(100 * time.Millisecond)
			d.ClearExpireCache(ctx)
		}
	}
}
