package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

func main() {

	var text string
	flag.StringVar(&text, "text", "闵行爆炸", "text")
	flag.Parse()

	client := impl.NewSougouClientHttp()
	searchRes, err := client.SougouSearch(context.Background(), text)

	fmt.Println()
	fmt.Println()
	fmt.Println()
	fmt.Println()
	fmt.Println()
	fmt.Println()
	if err != nil {
		fmt.Printf("执行 sougou 查询异常 => ERR: %v \n", err)
		return
	}
	fmt.Printf("执行 sougou 查询成功，结果 => %s \n", util.GetJSONIgnoreError(searchRes))
}
