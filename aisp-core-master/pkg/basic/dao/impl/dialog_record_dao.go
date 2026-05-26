package impl

import (
	"context"
	"errors"
	"fmt"
	"time"

	"git.in.zhihu.com/go/borm"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	"github.com/spf13/cast"
)

var DefaultDialogRecordDAO dao.DialogRecordDAO

type DialogRecordDAOImpl struct {
	db *borm.ORM
}

var _ dao.DialogRecordDAO = (*DialogRecordDAOImpl)(nil)

func NewDialogRecordDAO() dao.DialogRecordDAO {
	return &DialogRecordDAOImpl{
		db: mysql.AispCoreBorm,
	}
}

// SaveDialogs
// 批量保存对话记录（目前仅限于 分享时拷贝对话记录使用，其他业务场景使用注意 dialog 的 deleted 和 exceeded 状态）
func (d *DialogRecordDAOImpl) SaveDialogs(ctx context.Context, dtos []*model.DialogRecord) (mysql.Result, error) {
	insertResult := d.db.Create(ctx, dtos)
	if insertResult.Error != nil {
		return mysql.Result{}, insertResult.Error
	}
	return mysql.Result{LastInsertedID: insertResult.LastInsertedID, AffectedRows: insertResult.AffectedRows}, nil
}

// SaveOrUpdateDialog 更新或新增对话记录（更新状态下 数据为 未删除且未过期状态）
func (d *DialogRecordDAOImpl) SaveOrUpdateDialog(ctx context.Context, dto *model.DialogRecord) (mysql.Result, error) {
	dto.Deleted = cast.ToInt64(macro.Dict_No)
	dto.Exceeded = cast.ToInt64(macro.Dict_No)

	// 1. 查询是否存在旧的Group历史
	var dialogRecordBase model.DialogRecord
	var findOldGroupCount int64
	var findOldGroupErr error
	findOldGroupBormExpr := borm.Eq{
		"session_id":       dto.SessionId,
		"message_group_id": dto.MessageGroupId,
		"role_type":        dto.RoleType,
		"exceeded":         cast.ToInt64(macro.Dict_No)}
	if dto.MessageGroupId != "" && dto.MessageGroupId != dto.MessageId {
		// 判断逻辑命中 则说明当前场景为修改标题或重答
		findOldGroupCount, findOldGroupErr = d.db.Where(findOldGroupBormExpr).Model(&dialogRecordBase).Count(ctx)
		if findOldGroupErr != nil && !errors.Is(findOldGroupErr, borm.ErrRecordNotFound) {
			return mysql.Result{}, findOldGroupErr
		}
	}

	defer func() {
		if r := recover(); r != nil {
			log.Errorf(ctx, "panic in saveOrUpdateDialog: %v", r)
		}
	}()
	var dataId, affectedRows int64
	err := d.db.Transact(ctx, func(ctx context.Context, tx *borm.ORM) error {
		// 1. 如果 findOrlGroupCount 不等于0 则将旧的Group历史 置为 已过期
		if findOldGroupCount > 0 {
			updateOrlGroupResult := tx.Where(findOldGroupBormExpr).Model(&dialogRecordBase).UpdateRaw(ctx, map[string]interface{}{
				"exceeded": cast.ToInt64(macro.Dict_Yes),
			})
			if updateOrlGroupResult.Error != nil {
				return updateOrlGroupResult.Error
			}
		}

		// 判断messageId 是否存在
		oldData := &model.DialogRecord{}
		ormErr := tx.Where(borm.Eq{"session_id": dto.SessionId, "message_id": dto.MessageId}).One(ctx, oldData)
		if ormErr == nil || errors.Is(ormErr, borm.ErrRecordNotFound) {
			// 不存在 则新增
			if errors.Is(ormErr, borm.ErrRecordNotFound) {
				insertResult := tx.Create(ctx, dto)
				if insertResult.Error != nil {
					return insertResult.Error
				}
				dataId = insertResult.LastInsertedID
				affectedRows = insertResult.AffectedRows
			} else {
				// 存在则修改
				dataId = oldData.ID
				dto.ID = oldData.ID
				updateQueryResult := tx.Save(ctx, dto)
				if updateQueryResult.Error != nil {
					return updateQueryResult.Error
				}
				affectedRows = updateQueryResult.AffectedRows
			}
			return nil
		}
		return ormErr
	})

	if err != nil {
		return mysql.Result{}, err
	}

	return mysql.Result{LastInsertedID: dataId, AffectedRows: affectedRows}, nil
}

// GetDialogBySessionIdAndMessageId 根据SessionId 和 消息Id  获取会话
func (d *DialogRecordDAOImpl) GetDialogBySessionIdAndMessageId(ctx context.Context, sessionId int64, messageId string) (*model.DialogRecord, error) {
	var dialog *model.DialogRecord
	err := d.db.Where(borm.Eq{"session_id": sessionId, "message_id": messageId, "deleted": cast.ToInt64(macro.Dict_No)}).
		One(ctx, &dialog)
	if err != nil {
		return nil, err
	}
	return dialog, nil
}

// GetDialogByGroupIds 根据SessionId 和 GroupIds  获取会话
func (d *DialogRecordDAOImpl) GetDialogByGroupIds(ctx context.Context, sessionId int64, messageIds []string) ([]*model.DialogRecord, error) {
	var dialogs []*model.DialogRecord
	err := d.db.Where(borm.Eq{"session_id": sessionId, "message_group_id": messageIds, "deleted": cast.ToInt64(macro.Dict_No)}).
		All(ctx, &dialogs)
	if err != nil {
		fmt.Printf("EZRR %v\n", err)
		return []*model.DialogRecord{}, err
	}
	return dialogs, nil
}

func (d *DialogRecordDAOImpl) GetDialogsBySessionIdAndMaxCreateTime(ctx context.Context, sessionId int64, createAt time.Time) ([]*model.DialogRecord, error) {
	var dialogs []*model.DialogRecord
	err := d.db.Where(borm.Eq{"session_id": sessionId, "deleted": cast.ToInt64(macro.Dict_No)}).
		Where(borm.LTE{"created_at": createAt}).All(ctx, &dialogs)
	if err != nil {
		return []*model.DialogRecord{}, err
	}
	return dialogs, nil
}

// GetDialogListBySessionId 根据SessionId获取会话列表
func (d *DialogRecordDAOImpl) GetDialogListBySessionId(ctx context.Context, sessionId int64, limit uint64) ([]*model.DialogRecord, error) {
	var dialogRecords []*model.DialogRecord
	err := d.db.
		Where(borm.Eq{"session_id": sessionId, "deleted": cast.ToInt64(macro.Dict_No), "exceeded": cast.ToInt64(macro.Dict_No)}).
		Limit(int(limit)).
		OrderBy("-created_at").
		All(ctx, &dialogRecords)
	if err != nil {
		return []*model.DialogRecord{}, err
	}
	return dialogRecords, nil
}

func init() {
	DefaultDialogRecordDAO = NewDialogRecordDAO()
}
