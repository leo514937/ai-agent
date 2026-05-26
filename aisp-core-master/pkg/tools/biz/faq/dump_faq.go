package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"github.com/xuri/excelize/v2"
)

// 导出在线的faq到excel中
// go run pkg/tools/biz/faq/dump_faq.go
func main() {
	ctx := context.Background()

	maxSize := 100000
	operationBaseManagementService := operation_base.DefaultOperationBaseManagementService

	filterParams := &model.FilterParams{
		Page:     0,
		PageSize: maxSize,
		Status:   model.OperationBaseStatusOnline,
	}
	faqBases, _, err := operationBaseManagementService.ListFaqBase(ctx, filterParams)
	if err != nil {
		fmt.Println("faqBase error", err)
		return
	}

	f := excelize.NewFile()
	// 创建一个sheet
	index, err := f.NewSheet("Sheet1")
	if err != nil {
		fmt.Println(err)
		return
	}

	// 将新的sheet添加到Excel中
	f.SetActiveSheet(index)
	util.WriteCell(f, 1, "A", "id")
	util.WriteCell(f, 1, "B", "scene")
	util.WriteCell(f, 1, "C", "question")
	util.WriteCell(f, 1, "D", "match_type")
	util.WriteCell(f, 1, "E", "answer")

	beginIndex := 2
	for _, faqBase := range faqBases {
		util.WriteCell(f, beginIndex, "A", faqBase.Id)
		util.WriteCell(f, beginIndex, "B", faqBase.Scene)
		util.WriteCell(f, beginIndex, "C", faqBase.Question)
		util.WriteCell(f, beginIndex, "D", conf.ConvertMatchTypesToStr(conf.ConvertIntToFaqMatchTypeArray(faqBase.MatchType)))
		util.WriteCell(f, beginIndex, "E", faqBase.Answer)

		beginIndex += 1
		if beginIndex%100 == 0 {
			fmt.Println("processing. index=", beginIndex)
		}
	}

	// 保存Excel
	if err := f.SaveAs("faq_dump.xlsx"); err != nil {
		fmt.Println(err)
		return
	}

	fmt.Println("done")
}
