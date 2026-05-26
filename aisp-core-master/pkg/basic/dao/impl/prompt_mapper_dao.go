package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
)

var DefaultPromptMapperDAO dao.PromptMapperDAO

type PromptMapperDAOImpl struct {
	connection mysql.Connection
}

var _ dao.PromptMapperDAO = (*PromptMapperDAOImpl)(nil)

func NewPromptMapperDAO() dao.PromptMapperDAO {
	return &PromptMapperDAOImpl{
		connection: resource.MySQLAISPCore,
	}
}

func (*PromptMapperDAOImpl) columns() []string {
	return []string{
		dao.PromptMapperFieldID,
		dao.PromptMapperFieldPromptCode,
		dao.PromptMapperFieldPrompt,
		dao.PromptMapperFieldRemark,
		dao.PromptMapperFieldCreatedAt,
		dao.PromptMapperFieldUpdatedAt,
	}
}

func (*PromptMapperDAOImpl) insertColumns() []string {
	return []string{
		dao.PromptMapperFieldPromptCode,
		dao.PromptMapperFieldPrompt,
		dao.PromptMapperFieldRemark,
	}
}

func (d *PromptMapperDAOImpl) Insert(ctx context.Context, dto *model.PromptMapperDto) (int64, error) {
	logger := log.WithField(ctx, "InsertDto", dto)

	// 构建插入 SQL
	doCreate, args, err := sq.Insert(dao.PromptMapperTableName).Columns(d.insertColumns()...).Values(
		dto.PromptCode,
		dto.Prompt,
		dto.Remark,
	).ToSql()

	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "通过 createSQL 构建 SQL 失败")
		return 0, nil
	}

	// 执行插入
	result, err := d.connection.Exec(ctx, doCreate, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "通过 create 执行 SQL 失败")
		return 0, nil
	}

	lastId, err := result.LastInsertId()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "通过 create 获取最后插入的 id 失败")
	}
	return lastId, nil
}

func (d *PromptMapperDAOImpl) UpdateById(ctx context.Context, id int64, dto *model.PromptMapperDto) (int64, error) {
	logger := log.WithField(ctx, "UpdateById", id)

	updates := map[string]interface{}{}
	updates[dao.PromptMapperFieldPrompt] = dto.Prompt
	updates[dao.PromptMapperFieldRemark] = dto.Remark
	updates[dao.PromptMapperFieldUpdatedAt] = time.Now()

	// 构建修改 SQL
	doUpdate, args, err := sq.Update(dao.PromptMapperTableName).SetMap(updates).Where(
		sq.Eq{dao.PromptMapperFieldID: id}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "构建 SQL 失败")
		return 0, nil
	}

	// 执行修改
	result, err := d.connection.Exec(ctx, doUpdate, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, " 执行 SQL 失败")
		return 0, nil
	}

	rows, err := result.RowsAffected()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "获取更新行数失败")
	}
	return rows, nil
}

func (d *PromptMapperDAOImpl) DeleteById(ctx context.Context, id int64) (int64, error) {
	logger := log.WithField(ctx, "DeleteById", id)

	// 构建修改 SQL
	doDelete, args, err := sq.Delete(dao.PromptMapperTableName).Where(
		sq.Eq{dao.PromptMapperFieldID: id}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "构建 SQL 失败")
		return 0, nil
	}

	// 执行删除
	result, err := d.connection.Exec(ctx, doDelete, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "执行 SQL 失败")
		return 0, nil
	}

	rows, err := result.RowsAffected()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "获取删除行数失败")
	}
	return rows, nil
}

func (d *PromptMapperDAOImpl) GetById(ctx context.Context, id int64) (*model.PromptMapper, error) {
	logger := log.WithField(ctx, "GetById", id)

	// 构建选择查询的 SQL
	querySql, args, err := sq.Select(d.columns()...).From(dao.PromptMapperTableName).Where(
		sq.Eq{dao.PromptMapperFieldID: id}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "构建 SQL 失败")
		return nil, err
	}

	// 执行选择查询
	row := d.connection.QueryRow(ctx, querySql, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "查询 SQL 失败")
		return nil, err
	}
	if row == nil {
		return nil, nil
	}

	prompt := &model.PromptMapper{}
	err = row.Scan(
		&prompt.ID,
		&prompt.PromptCode,
		&prompt.Prompt,
		&prompt.Remark,
		&prompt.CreatedAt,
		&prompt.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	return prompt, nil
}

func (d *PromptMapperDAOImpl) GetByCode(ctx context.Context, code string) (*model.PromptMapper, error) {
	logger := log.WithField(ctx, "GetByCode", code)

	// 构建选择查询的 SQL
	querySql, args, err := sq.Select(d.columns()...).From(dao.PromptMapperTableName).Where(
		sq.Eq{dao.PromptMapperFieldPromptCode: code}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "构建 SQL 失败")
		return nil, err
	}

	// 执行选择查询
	row := d.connection.QueryRow(ctx, querySql, args...)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "查询 SQL 失败")
		return nil, err
	}
	if row == nil {
		return nil, nil
	}

	prompt := &model.PromptMapper{}
	err = row.Scan(
		&prompt.ID,
		&prompt.PromptCode,
		&prompt.Prompt,
		&prompt.Remark,
		&prompt.CreatedAt,
		&prompt.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	return prompt, nil
}

func init() {
	DefaultPromptMapperDAO = NewPromptMapperDAO()
}
