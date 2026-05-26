package ask_related_word

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/utils"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/spf13/cast"
)

const batchSize = 5
const readIncrementalDataSQL = `select doc_id,doc_type from ai.pd_related_question_from_answer_content where p_date='%s'`

type relatedQuestionFromAnswerContent struct {
	docId   int64
	docType string
}

func RunReadHiveAndRefreshAskRelatedWord() error {
	ctx := context.TODO()
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "core.crontab.ask_related_word",
		"job":  "readHiveAndRefreshAskRelatedWord",
	})
	logger.Infof(ctx, "start sync job")

	resources.Init(graph_constant.ApiStreamChat)
	hiveClient := resource.NewHiveClient()
	processor := process.NewContentActivityProcessor()

	// 获取昨天的pDate
	pDate := utils.TimeAgo(24 * time.Hour).Format("2006-01-02")
	sql := fmt.Sprintf(readIncrementalDataSQL, pDate)
	cursor := hiveClient.GetCursor()
	cursor.Exec(ctx, "set hive.strict.checks.large.query=false")
	cursor.Exec(ctx, "set hive.mapred.mode=nonstrict")
	cursor.Exec(ctx, sql)
	if cursor.Err != nil {
		logger.Errorf(ctx, "Hive Err:%v, sql=>%s", cursor.Err, sql)
		return cursor.Err
	}

	batchWorker := util.NewWork[*module.ContentActivityEvent](batchSize)
	batchWorker.Consumer(func(msg *module.ContentActivityEvent) error {
		marshalJsonByteArray, errJson := json.Marshal(*msg)
		if errJson != nil {
			logger.Infof(ctx, "marshalJson error: %s", errJson)
			return errJson
		}
		logger.Infof(ctx, "print source:%+v, json:%s", msg, string(marshalJsonByteArray))
		runErr := processor.DoHandleProcess(ctx, marshalJsonByteArray, true, true)
		if runErr != nil {
			logger.Infof(ctx, "run data:%+v error: %v \n", marshalJsonByteArray, runErr)
		}
		return runErr
	})
	batchWorker.Producer(func(producer *util.BatchWorkerProducer[*module.ContentActivityEvent]) {
		for cursor.HasMore(ctx) {
			tmp := relatedQuestionFromAnswerContent{}
			cursor.FetchOne(ctx, &tmp.docId, &tmp.docType)
			producer.Put(&module.ContentActivityEvent{OutId: cast.ToString(tmp.docId), ContentType: strings.ToUpper(tmp.docType)})
		}
	})
	batchWorker.Wait()
	batchWorkerResult := batchWorker.GetResult()
	logger.Infof(ctx, "refresh total:%d, consumer:%d, done:%d, error:%d",
		batchWorkerResult.TotalCount, batchWorkerResult.ConsumerCount, batchWorkerResult.DoneCount, batchWorkerResult.ErrorCount)
	return nil
}
