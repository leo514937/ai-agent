package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/google/uuid"
)

func main() {

	var text string
	flag.StringVar(&text, "text", "夸克搜索", "text")
	flag.Parse()

	client := impl.DefaultQuarkSearchClient
	searchRes, err := client.Search(context.Background(), text, 10, uuid.NewString())

	fmt.Println()

	if err != nil {
		fmt.Printf("执行 quark 查询异常 => ERR: %v \n", err)
		return
	}
	fmt.Printf("执行 quark 查询成功，结果 => %s \n", util.GetJSONIgnoreError(searchRes))
}
