package main

import (
	"context"
	"fmt"
	"time"

	chat_content_thrift "git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/content"
	service2 "git.in.zhihu.com/zhihu/aisp-core/pkg/business/censor/service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
)

// go run pkg/tools/biz/dashboard/main.go
func main() {
	ctx := context.Background()
	service := operation_base.DefaultOperationBaseManagementService

	currentTime := time.Now()                  // 获取当前时间
	yesterday := currentTime.AddDate(0, 0, -1) // 减去一天得到昨天的日期

	// dashboard
	res, cnt, err := service.ListLogTracing(ctx, &model.FilterParams{
		Page:           0,
		PageSize:       10,
		Scene:          "直答专业版",
		Query:          "总结",
		CreatedAtBegin: &yesterday,
		CreatedAtEnd:   &currentTime,
	})
	if err != nil {
		fmt.Println(fmt.Sprintf("ListLogTracing error: %v", err))
	}

	fmt.Println(fmt.Sprintf("ListLogTracing res: %v, cnt: %v", util.GetJSONIgnoreError(res), cnt))

	// rpc
	res2, err := service2.DefaultChatService.ChatRecordQuery(ctx, &chat_content_thrift.ChatRecordRequest{
		MemberID:         lo.ToPtr(int64(117223006)),
		RequestTimeStart: lo.ToPtr(int64(1730197103)),
	})
	if err != nil {
		fmt.Println(fmt.Sprintf("Error ChatRecordQuery => %v", err))
		return
	}
	fmt.Println(fmt.Sprintf("ChatRecordQuery => %v", util.GetJSONIgnoreError(res2)))
}
