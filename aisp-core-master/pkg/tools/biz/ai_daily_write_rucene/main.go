package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	sq "github.com/Masterminds/squirrel"
)

/*
从TiDB读取快照，解析，批量写rucene数据
可用于全量刷索引
参数：
start: 起始日期，2025-04-13,必传
end:   结束日期，2025-04-13，必传
token：某个快照的数据

执行命令 ： go run pkg/tools/biz/ai_daily_write_rucene/main.go -start=2025-04-23 -end=2025-04-23 -token=abc
*/
func main() {
	start := flag.String("start", "", "start date")
	end := flag.String("end", "", "end date")
	token := flag.String("token", "", "hash_token")
	flag.Parse()
	if *start == "" || *end == "" || *start > *end {
		os.Exit(1)
	}
	ctx := context.Background()
	logger := log.WithFields(ctx, map[string]interface{}{
		"token": token,
		"start": *start,
		"end":   *end,
	})
	startTime, err := time.Parse("2006-01-02", *start)
	if err != nil {
		os.Exit(1)
	}
	endTime, err := time.Parse("2006-01-02", *end)
	if err != nil {
		os.Exit(1)
	}
	t := startTime
	// 逐天处理数据
	for t.Compare(endTime) <= 0 {
		date := t.Format("2006-01-02")
		err := DealDataByDate(ctx, date, *token)
		if err != nil {
			fmt.Println("Current Date:", date)
			os.Exit(1)
		}
		t = t.AddDate(0, 0, 1)
	}
	logger.Infof(ctx, "Finish Success")
}

func DealDataByDate(ctx context.Context, date, token string) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"token": token,
		"date":  date,
	})
	// 构建选择查询的 SQL
	where := sq.And{
		sq.GtOrEq{
			"generate_date": date,
		}, sq.LtOrEq{
			"generate_date": date,
		},
	}
	if token != "" {
		where = append(where, sq.Eq{
			"hash_token": token,
		})
	}
	querySql, args, err := sq.Select([]string{"hash_token", "generate_date", "json_content", "created_at"}...).From((&model.TableDailySnapshot{}).TableName()).Where(where).ToSql()
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "failed to build sql.err=%v", err)
		return err
	}
	rows, err := resource.MySQLAISPCore.Query(ctx, querySql, args...)
	if err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil
		}
		logger.WithError(ctx, err).Error(ctx, "failed to query.err=%v", err)
		return err
	}
	defer rows.Close()
	for rows.Next() {
		snapshot := &model.TableDailySnapshot{}
		err = rows.Scan(
			&snapshot.HashToken,
			&snapshot.GenerateDate,
			&snapshot.JsonContent,
			&snapshot.CreatedAt,
		)
		if err != nil {
			logger.Errorf(ctx, "failed to scan.err=%v", err)
			return err
		}
		err = DealSnapShot(ctx, snapshot.HashToken, snapshot.JsonContent, snapshot.CreatedAt)
		if err != nil {
			logger.Errorf(ctx, "DealSnapShot failed.err=%v", err)
			return err
		}
	}
	return nil
}

func DealSnapShot(ctx context.Context, hashToken, snapshot string, createdTime time.Time) error {
	questionDetails := make([]*model.RedisQuestionDetail, 0)
	err := json.Unmarshal([]byte(snapshot), &questionDetails)
	if err != nil {
		log.Errorf(ctx, "[DealSnapShot] Unmarshal error: %v", err)
		return err
	}
	playListData := &model.PlayListData{
		FinalQuestionDetails: questionDetails,
		HashToken:            hashToken,
		CardGenerateTime:     createdTime,
	}
	saveTiDBLogic := logic.NewSaveTiDBQuestionLogic("", nil)
	err = saveTiDBLogic.SaveTiDB(ctx, playListData)
	if err != nil {
		log.Errorf(ctx, "[DealSnapShot] SaveTiDB error: %v", err)
		return err
	}
	saveRuceneLogic := logic.NewSaveRuceneLogic("", nil)
	err = saveRuceneLogic.SaveData(ctx, playListData)
	if err != nil {
		log.Errorf(ctx, "[DealSnapShot] SaveData error: %v", err)
		return err
	}
	return nil
}
