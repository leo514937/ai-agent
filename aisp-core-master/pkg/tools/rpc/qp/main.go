package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

// go run pkg/tools/rpc/qp/main.go
func main() {
	ctx := context.Background()
	query := flag.String("query", "美国为什么现在有那么多流浪汉？", "input texts")
	flag.Parse()

	qpResponse := impl.DefaultQpImpl.GetQueryProfile(ctx, *query)
	fmt.Println(fmt.Sprintf("qp result:%v", util.GetJSONIgnoreError(qpResponse)))

	quResponse := impl.DefaultQpImpl.GetQueryKeyWords(ctx, *query)
	fmt.Println(fmt.Sprintf("qu result:%v", util.GetJSONIgnoreError(quResponse)))
}
