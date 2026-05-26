package dao

import (
	"fmt"
	"testing"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	sq "github.com/Masterminds/squirrel"
)

func TestExistQuestionIOs(t *testing.T) {
	questionIDs := []string{"a", "b", "c"}
	query, args, err := sq.Select("question_id").From((&model.TableQuestionDetailCnt{}).TableName()).Where(sq.Eq{
		"question_id": questionIDs,
	}).ToSql()
	fmt.Println("Select:", query, args, err)
	datas := []*model.TableQuestionDetailCnt{
		{
			ID:             1,
			QuestionID:     "1",
			ShareCount:     1,
			ShowCount:      1,
			FirstShareTime: 1,
			CreatedAt:      1,
		},
		{
			ID:             2,
			QuestionID:     "2",
			ShareCount:     2,
			ShowCount:      2,
			FirstShareTime: 2,
			CreatedAt:      2,
		},
	}
	tableModel := &model.TableQuestionDetailCnt{}
	insertBuilder := sq.
		Insert(tableModel.TableName()).Columns(tableModel.InsertColumns()...)
	for _, v := range datas {
		insertBuilder = insertBuilder.Values(v.QuestionID, v.ShareCount, v.ShowCount, v.FirstShareTime, v.CreatedAt)
	}
	query2, args2, err2 := insertBuilder.ToSql()
	fmt.Println("Insert:", query2, args2, err2)
}
