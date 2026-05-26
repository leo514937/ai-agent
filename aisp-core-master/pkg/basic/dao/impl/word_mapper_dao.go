package impl

import (
	"context"
	"fmt"
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_tab/constants"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
	"github.com/pkg/errors"
	"github.com/spf13/cast"
)

var DefaultWordMapperDAO dao.WordMapperDAO

func init() {
	DefaultWordMapperDAO = NewWordMapperDAO()
}

type WordMapperDAOImpl struct {
	connection  mysql.Connection
	idGenerator dao.IDGenerator
}

var _ dao.WordMapperDAO = (*WordMapperDAOImpl)(nil)

func NewWordMapperDAO() dao.WordMapperDAO {
	return &WordMapperDAOImpl{
		connection:  resource.MySQLAISPCore,
		idGenerator: dao.DefaultIDGenerator,
	}
}

func (*WordMapperDAOImpl) columns() []string {
	return []string{
		dao.WordMapperFieldID,
		dao.WordMapperFieldWordId,
		dao.WordMapperFieldWordType,
		dao.WordMapperFieldWord,
		dao.WordMapperFieldSourceId,
		dao.WordMapperFieldDeleted,
		dao.WordMapperFieldCreatedAt,
		dao.WordMapperFieldUpdatedAt,
	}
}

func (*WordMapperDAOImpl) insertColumns() []string {
	return []string{
		dao.WordMapperFieldWordId,
		dao.WordMapperFieldWordType,
		dao.WordMapperFieldWord,
		dao.WordMapperFieldSourceId,
		dao.WordMapperFieldDeleted,
	}
}

func (d *WordMapperDAOImpl) DelByWordId(ctx context.Context, wordId int64) (int64, error) {
	logger := log.WithField(ctx, "DelByWordId", wordId)

	// 构建删除的 SQL
	delSql, delArgs, delErr := sq.Update(dao.WordMapperTableName).Set(dao.WordMapperFieldDeleted, cast.ToInt64(macro.Dict_Yes)).Where(
		sq.Eq{
			dao.WordMapperFieldWordId:  wordId,
			dao.WordMapperFieldDeleted: cast.ToInt64(macro.Dict_No),
		}).ToSql()
	if delErr != nil {
		logger.WithError(ctx, delErr).Error(ctx, "构建 逻辑删除 SQL 失败")
		return 0, delErr
	}

	// 执行逻辑删除
	result, err := d.connection.Exec(ctx, delSql, delArgs...)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "执行 逻辑删除 SQL 失败 error => %v", err)
		return 0, delErr
	}

	rows, err := result.RowsAffected()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "获取删除行数失败")
	}
	return rows, nil
}

func (d *WordMapperDAOImpl) DelByWordIdAndType(ctx context.Context, wordId int64, wordType int32) (int64, error) {
	logger := log.WithField(ctx, "DelByWordIdAndType", wordId)

	// 构建删除的 SQL
	delSql, delArgs, delErr := sq.Update(dao.WordMapperTableName).Set(dao.WordMapperFieldDeleted, cast.ToInt64(macro.Dict_Yes)).Where(
		sq.Eq{
			dao.WordMapperFieldWordId:   wordId,
			dao.WordMapperFieldWordType: wordType,
		}).ToSql()
	if delErr != nil {
		logger.WithError(ctx, delErr).Error(ctx, "构建 逻辑删除 SQL 失败")
		return 0, delErr
	}

	// 执行逻辑删除
	result, err := d.connection.Exec(ctx, delSql, delArgs...)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "执行 逻辑删除 SQL 失败 error => %v", err)
		return 0, delErr
	}

	rows, err := result.RowsAffected()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "获取删除行数失败")
	}
	return rows, nil
}

func (d *WordMapperDAOImpl) UpdateWordById(ctx context.Context, wordId int64, word string) (int64, error) {
	logger := log.WithField(ctx, "UpdateWordById", wordId)

	// 构建update的 SQL
	delSql, delArgs, delErr := sq.Update(dao.WordMapperTableName).Set(dao.WordMapperFieldWord, word).Where(
		sq.Eq{dao.WordMapperFieldWordId: wordId}).ToSql()
	if delErr != nil {
		logger.WithError(ctx, delErr).Error(ctx, "构建 逻辑更新 SQL 失败")
		return 0, delErr
	}

	// 执行逻辑
	result, err := d.connection.Exec(ctx, delSql, delArgs...)
	if err != nil {
		logger.WithError(ctx, err).Errorf(ctx, "执行 逻辑更新 SQL 失败 error => %v", err)
		return 0, delErr
	}

	rows, err := result.RowsAffected()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "获取更新行数失败")
	}
	return rows, nil
}

func (d *WordMapperDAOImpl) GetByWordId(ctx context.Context, wordId int64) (*model.WordMapper, error) {
	logger := log.WithField(ctx, "GetByWordId", wordId)

	// 构建选择查询的 SQL
	querySql, args, err := sq.Select(d.columns()...).From(dao.WordMapperTableName).Where(
		sq.Eq{dao.WordMapperFieldWordId: wordId}).ToSql()
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

	word := &model.WordMapper{}
	err = row.Scan(
		&word.ID,
		&word.WordId,
		&word.WordType,
		&word.Word,
		&word.SourceId,
		&word.Deleted,
		&word.CreatedAt,
		&word.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	return word, nil
}

func (d *WordMapperDAOImpl) GetByWordIdAndType(ctx context.Context, wordId int64, wordType int32) (*model.WordMapper, error) {
	logger := log.WithField(ctx, "GetByWordIdAndType", wordId)

	// 构建选择查询的 SQL
	querySql, args, err := sq.Select(d.columns()...).From(dao.WordMapperTableName).Where(
		sq.Eq{
			dao.WordMapperFieldWordId:   wordId,
			dao.WordMapperFieldWordType: wordType,
		}).ToSql()
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

	word := &model.WordMapper{}
	err = row.Scan(
		&word.ID,
		&word.WordId,
		&word.WordType,
		&word.Word,
		&word.SourceId,
		&word.Deleted,
		&word.CreatedAt,
		&word.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	return word, nil
}

func (d *WordMapperDAOImpl) GetByWordAndType(ctx context.Context, wordStr string, wordType int32) (*model.WordMapper, error) {
	logger := log.WithField(ctx, "GetByWordAndType", wordStr)

	// 构建选择查询的 SQL
	querySql, args, err := sq.Select(d.columns()...).From(dao.WordMapperTableName).Where(
		sq.Eq{
			dao.WordMapperFieldWord:     wordStr,
			dao.WordMapperFieldWordType: wordType,
		}).ToSql()
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

	word := &model.WordMapper{}
	err = row.Scan(
		&word.ID,
		&word.WordId,
		&word.WordType,
		&word.Word,
		&word.SourceId,
		&word.Deleted,
		&word.CreatedAt,
		&word.UpdatedAt,
	)
	if err != nil {
		return nil, err
	}
	return word, nil
}

func (d *WordMapperDAOImpl) WordExist(ctx context.Context, word string, wordTypes []int32) bool {
	logger := log.WithField(ctx, "WordExist", word)

	countQuerySql, countArgs, sqlErr := sq.Select("count(1)").From(dao.WordMapperTableName).
		Where(sq.And{sq.Eq{dao.WordMapperFieldWord: strings.TrimSpace(word)}, sq.Eq{dao.WordMapperFieldWordType: wordTypes}}).
		ToSql()
	if sqlErr != nil {
		logger.WithError(ctx, sqlErr).Error(ctx, "构建 SQL count 失败")
		return false
	}

	// 执行查询
	var count int
	countExecErr := d.connection.QueryRow(ctx, countQuerySql, countArgs...).Scan(&count)
	if countExecErr != nil {
		logger.WithError(ctx, countExecErr).Error(ctx, "执行 count  SQL 失败")
		return false
	}

	return count > 0
}

func (d *WordMapperDAOImpl) GetWordIdAndCreate(ctx context.Context, wordDto *model.WordMapperCreateDto) (int64, error) {
	logger := log.WithField(ctx, "word", wordDto)

	var resWordId = constants.DefDataId
	var resErr error

	// 构建选择查询的 SQL
	countQuerySql, countArgs, countErr := sq.Select(dao.WordMapperFieldWordId, dao.WordMapperFieldDeleted).From(dao.WordMapperTableName).Where(sq.Eq{
		dao.WordMapperFieldWord:     strings.TrimSpace(wordDto.Word),
		dao.WordMapperFieldWordType: wordDto.WordType,
	}).ToSql()
	if countErr != nil {
		logger.WithError(ctx, countErr).Error(ctx, "构建 SQL count 失败")
		return 0, countErr
	}

	// 执行查询
	word := &model.WordMapper{}
	rows, queryErr := d.connection.Query(ctx, countQuerySql, countArgs...)
	defer func() {
		if rows != nil {
			rows.Close()
		}
	}()

	if queryErr != nil {
		logger.WithError(ctx, queryErr).Error(ctx, "执行 query 失败")
		return 0, queryErr
	}

	if rows.Next() {
		err := rows.Scan(
			&word.WordId, &word.Deleted,
		)
		if err != nil {
			logger.WithError(ctx, queryErr).Error(ctx, "row scan error")
		}
	}

	// 当检索有结果，判断是否被禁用，如果被禁用则返回错误，未被禁用返回 wordId
	if word.WordId != 0 {
		if word.Deleted == cast.ToInt64(macro.Dict_Yes) {
			return 0, errors.Errorf("当前词已被禁用 => %s", wordDto.Word)
		} else {
			return word.WordId, nil
		}
	}

	// 没有找到 wordId，创建 wordId 并写入 mysql
	maxRetry := 2
	for retry := 0; retry < maxRetry; retry++ {
		// 如果在历史记录中未找到，则创建 wordId
		wordIdTmp, err := d.idGenerator.GenerateIDByType(ctx, dao.GeneratorIdTypeWord)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "通过 createSQL 创建 wordId 失败")
			resErr = err
			continue
		}

		// 构建插入 SQL
		doCreate, args, err := sq.Insert(dao.WordMapperTableName).Columns(d.insertColumns()...).Values(
			wordIdTmp,
			wordDto.WordType,
			strings.TrimSpace(wordDto.Word),
			wordDto.SourceId,
			cast.ToInt64(macro.Dict_No),
		).ToSql()
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "通过 createSQL 构建 SQL 失败")
			resErr = err
			continue
		}

		// 执行插入
		result, err := d.connection.Exec(ctx, doCreate, args...)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "通过 create 执行 SQL 失败")
			resErr = err
			continue
		}

		_, err = result.LastInsertId()
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "通过 create 获取最后插入的 id 失败")
			resErr = err
			continue
		}

		resWordId = wordIdTmp
		break
	}

	logger.Info(ctx, fmt.Sprintf("created word %s", wordDto.Word))
	return resWordId, resErr
}

func (d *WordMapperDAOImpl) GetValidWordByType(ctx context.Context, wordType []proto.QueryType, limit uint64) ([]*model.WordMapper, error) {
	logger := log.WithField(ctx, "wordType", wordType)

	// 构建选择查询的 SQL
	countQuerySql, countArgs, countErr := sq.Select(dao.WordMapperFieldWordId, dao.WordMapperFieldWord).From(dao.WordMapperTableName).
		Where(sq.And{sq.NotEq{
			dao.WordMapperFieldDeleted: cast.ToInt64(macro.Dict_Yes),
		}, sq.Eq{
			dao.WordMapperFieldWordType: wordType,
		}}).Limit(limit).ToSql()
	if countErr != nil {
		logger.WithError(ctx, countErr).Error(ctx, "构建 SQL count 失败")
		return nil, countErr
	}

	// 执行查询
	rows, queryErr := d.connection.Query(ctx, countQuerySql, countArgs...)
	defer func() {
		if rows != nil {
			rows.Close()
		}
	}()

	if queryErr != nil {
		logger.WithError(ctx, queryErr).Error(ctx, "执行 query 失败")
		return nil, queryErr
	}

	var words []*model.WordMapper
	for rows.Next() {
		word := &model.WordMapper{}

		err := rows.Scan(
			&word.WordId, &word.Word,
		)
		if err != nil {
			logger.WithError(ctx, queryErr).Error(ctx, "row scan error")
		} else {
			words = append(words, word)
		}
	}

	return words, nil
}
