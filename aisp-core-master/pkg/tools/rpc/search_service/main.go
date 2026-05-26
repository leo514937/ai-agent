package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/one-rpc-go/thrift-search_service/search_service_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/samber/lo"
)

// go run pkg/tools/rpc/search_service/main.go
func main() {
	ctx := context.Background()
	text := flag.String("text", "讲述LSTM", "input texts")
	flag.Parse()

	request := rpc.SearchServiceRequest{
		Offset: 0,
		Limit:  16,
		Vertical: []search_service_thrift.Vertical{
			search_service_thrift.Vertical_CONTENT,
			search_service_thrift.Vertical_DomesticScholar,
			search_service_thrift.Vertical_ForeignScholar},
		SearchFilterOption: &search_service_thrift.SearchFilterOption{
			HighQuality: lo.ToPtr(true),
		},
		Query:     *text,
		TimeAfter: 0,
		MemberID:  117223006,
	}

	response := impl.DefaultSearchServiceRpcImpl.Search(ctx, request)
	fmt.Println(fmt.Sprintf("search service result:%v", util.GetJSONIgnoreError(response)))
}
