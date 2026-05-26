package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/search_recall"
)

func main() {
	var text string
	flag.StringVar(&text, "text", "闵行爆炸", "text")
	flag.Parse()

	searchTypes := []search_recall.OutSiteSearchRecallType{
		//search_recall.OutSiteSearchRecallTypeBing,
		search_recall.OutSiteSearchRecallTypeCloudSwaySerp,
	}

	ctx := context.TODO()
	recallService := search_recall.NewOutSiteSearchRecallService()

	for _, searchType := range searchTypes {
		result := recallService.OutSiteSearchRecall(ctx, searchType, text, 10, "traceId", nil)
		fmt.Printf("输出[%s]结果: %s \n", searchType.String(), util.GetJSONIgnoreError(result))
	}
}
