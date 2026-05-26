package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"io"
	"os"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/module"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

const batchSize = 10

func main() {
	// 打开CSV文件
	file, err := os.Open("answer_data.csv")
	if err != nil {
		fmt.Println("Error:", err)
		return
	}
	defer file.Close()

	initIndex := 0
	ctx := context.Background()
	resources.Init(graph_constant.ApiStreamChat)
	processor := process.NewContentActivityProcessor()
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "offline.refresh_answer_ask_related_word_cache",
	})

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
		// 创建CSV读取器
		reader := csv.NewReader(file)
		reader.LazyQuotes = true
		index := 0
		// 读取CSV文件的每一行
		for {
			record, rErr := reader.Read()
			if rErr == io.EOF {
				break // 结束读取
			}
			if rErr != nil {
				logger.Errorf(ctx, "Error: %v", rErr)
				return
			}

			if index != 0 && index > initIndex {
				// 获取并处理第一列数据
				firstColumn := record[0]
				producer.Put(&module.ContentActivityEvent{OutId: firstColumn, ContentType: "ANSWER"})
			}
			index++
		}
	})
	batchWorker.Wait()
	batchWorkerResult := batchWorker.GetResult()
	logger.Infof(ctx, "refresh total:%d, consumer:%d, done:%d, error:%d",
		batchWorkerResult.TotalCount, batchWorkerResult.ConsumerCount, batchWorkerResult.DoneCount, batchWorkerResult.ErrorCount)
}
