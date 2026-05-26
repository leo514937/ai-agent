package dao

import (
	"context"
	"database/sql"
	"errors"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/mysql"
	sq "github.com/Masterminds/squirrel"
)

type QuestionDetailCntDAO interface {
	ExistQuestionIDs(ctx context.Context, questionIDs []string) (map[string]struct{}, error)
	BatchCreateQuestionDetailCnt(ctx context.Context, datas []*model.TableQuestionDetailCnt) error
}

type QuestionDetailCntDAOImpl struct {
	connection mysql.Connection
}

func newQuestionDetailCntDAOImpl() QuestionDetailCntDAO {
	return &QuestionDetailCntDAOImpl{
		connection: resource.MySQLAISPCore,
	}
}

var DefaultQuestionDetailCntDAO QuestionDetailCntDAO

func init() {
	DefaultQuestionDetailCntDAO = newQuestionDetailCntDAOImpl()
}

func (d *QuestionDetailCntDAOImpl) ExistQuestionIDs(ctx context.Context, questionIDs []string) (map[string]struct{}, error) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"question_ids": questionIDs,
	})
	existMap := make(map[string]struct{})
	query, args, err := sq.Select("question_id").From((&model.TableQuestionDetailCnt{}).TableName()).Where(sq.Eq{
		"question_id": questionIDs,
	}).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "[GetQuestionDetailByQuestionIDs] failed to build sql")
		return nil, err
	}
	rows, err := d.connection.Query(ctx, query, args...)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return existMap, nil
		}
		logger.WithError(ctx, err).Error(ctx, "[GetQuestionDetailByQuestionIDs] failed to query")
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var qid string
		err = rows.Scan(
			&qid,
		)
		if err != nil {
			logger.WithError(ctx, err).Error(ctx, "[GetQuestionDetailByQuestionIDs] failed to scan")
			return nil, err
		}
		existMap[qid] = struct{}{}
	}
	return existMap, nil
}

func (d *QuestionDetailCntDAOImpl) BatchCreateQuestionDetailCnt(ctx context.Context, datas []*model.TableQuestionDetailCnt) error {
	tableModel := &model.TableQuestionDetailCnt{}
	insertBuilder := sq.
		Insert(tableModel.TableName()).Columns(tableModel.InsertColumns()...)
	for _, v := range datas {
		insertBuilder = insertBuilder.Values(v.QuestionID, v.ShareCount, v.ShowCount, v.FirstShareTime, v.CreatedAt)
	}
	query, args, err := insertBuilder.ToSql()
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[BatchCreateDailySnapshot] failed to generate sql.err=%v", err)
		return err
	}
	_, err = d.connection.Exec(ctx, query, args...)
	if err != nil {
		log.WithError(ctx, err).Errorf(ctx, "[BatchCreateDailySnapshot] failed to exec sql.err=%v", err)
		return err
	}
	return nil
}
