package main

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/search_recall"
	"github.com/tealeg/xlsx"
)

func main() {

	var topK int32 = 5
	searchTypes := []search_recall.OutSiteSearchRecallType{
		search_recall.OutSiteSearchRecallTypeQuark,
	}

	recallService := search_recall.NewOutSiteSearchRecallService()

	file, err := xlsx.OpenFile("query_template.xlsx")
	if err != nil {
		fmt.Println(err)
		return
	}

	// 获取第1个工作表
	sheet1 := file.Sheets[0]

	taskSheetMap := make(map[search_recall.OutSiteSearchRecallType]*xlsx.Sheet, 0)
	for _, searchType := range searchTypes {
		sheet, _ := file.AddSheet(searchType.String())
		taskSheetMap[searchType] = sheet
	}

	ctx := context.TODO()

	syncMap := util.NewSyncMap[int, map[search_recall.OutSiteSearchRecallType][]*rpc.OutSiteSearchRecallAnswerResult]()
	batchWorker := util.NewWork[*serperMsg](5)
	batchWorker.Consumer(func(msg *serperMsg) error {
		fmt.Println(*msg)
		resMap := make(map[search_recall.OutSiteSearchRecallType][]*rpc.OutSiteSearchRecallAnswerResult)
		for _, searchType := range searchTypes {
			rpcRes := recallService.OutSiteSearchRecall(ctx, searchType, msg.query, topK, "", nil)
			resMap[searchType] = rpcRes
		}
		syncMap.Set(msg.index, resMap)
		return nil
	})
	batchWorker.Producer(func(producer *util.BatchWorkerProducer[*serperMsg]) {
		// 遍历所有行
		for i, row := range sheet1.Rows {
			if i == 0 {
				continue
			}
			producer.Put(&serperMsg{index: i, query: row.Cells[0].String()})
		}
	})
	batchWorker.Wait()
	batchWorkerResult := batchWorker.GetResult()

	// 遍历所有行
	for i, row := range sheet1.Rows {
		if i == 0 {
			for _, sheet := range taskSheetMap {
				sheetRow := sheet.AddRow()
				sheetRow.AddCell().SetValue("Query")
				sheetRow.AddCell().SetValue("Rank")
				sheetRow.AddCell().SetValue("Title")
				sheetRow.AddCell().SetValue("Url")
				sheetRow.AddCell().SetValue("Snippet")
				sheetRow.AddCell().SetValue("MainText")
			}
			continue
		}

		searchRes, isOk := syncMap.Get(i)
		if !isOk {
			continue
		}

		query := row.Cells[0].String()
		for searchType, searchRpcRes := range searchRes {
			sheet := taskSheetMap[searchType]
			for j, item := range searchRpcRes {
				r := sheet.AddRow()
				r.AddCell().SetValue(query)
				r.AddCell().SetValue(j + 1)
				r.AddCell().SetValue(item.Name)
				r.AddCell().SetValue(item.Url)
				r.AddCell().SetValue(item.Snippet)
				r.AddCell().SetValue(item.MainText)
			}
		}
	}

	fmt.Printf("输出执行结果: %s \n", util.GetJSONIgnoreError(batchWorkerResult))

	fileNames := []string{"eval"}
	for _, searchType := range searchTypes {
		fileNames = append(fileNames, searchType.String())
	}
	// 保存文件
	err = file.Save(fmt.Sprintf("%s-%s.xlsx", strings.Join(fileNames, "-"), util.FormatTime2yyyyMMddHHmmss(time.Now())))
	if err != nil {
		fmt.Println(err)
		return
	}
}

type SearchResponse struct {
	BingRes   []*rpc.OutSiteSearchRecallAnswerResult
	SerperRes []*rpc.OutSiteSearchRecallAnswerResult
}

type serperMsg struct {
	index int
	query string
}
