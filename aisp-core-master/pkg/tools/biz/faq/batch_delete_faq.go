package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
)

// 批量删除faq
func main() {
	operationBaseManagementService := operation_base.DefaultOperationBaseManagementService

	pageSize := 10000
	ctx := context.Background()
	params := &model.FilterParams{
		Page:      0,
		PageSize:  pageSize,
		Status:    model.OperationBaseStatusOnline,
		Scene:     "search_tab",
		MatchType: []conf.FaqMatchType{},
	}

	allFaqBases, _, err := operationBaseManagementService.ListFaqBase(ctx, params)
	if err != nil {
		panic(err)
	}

	for index, faqBase := range allFaqBases {
		faqBase.StatusCode = model.OperationBaseStatusDeleted
		_, err := operationBaseManagementService.UpdateFaqBase(ctx, faqBase)
		if err != nil {
			fmt.Printf("delete error. id=%d, query=%s, err=%v", faqBase.Id, faqBase.Question, err)
			return
		}
		if index%100 == 0 {
			fmt.Printf("delete done. index=%d", index)
		}
	}

	fmt.Printf("delete all done.")
}
