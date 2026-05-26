package main

import (
	"context"
	"flag"
	"fmt"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

// go run pkg/tools/rpc/ucp/main.go
func main() {
	ctx := context.Background()
	texts := flag.String("texts", "高考如何报志愿", "input texts")
	flag.Parse()
	textSlice := strings.Split(*texts, ",")

	response := impl.DefaultUcpGrpcImpl.BatchGetBayesTagInfos(ctx, textSlice)
	fmt.Println(fmt.Sprintf("gen bayes tag result:%v", util.GetJSONIgnoreError(response)))
}
