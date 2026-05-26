package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
)

func main() {

	var text string
	flag.StringVar(&text, "text", "如何看待金价走势", "text")
	flag.Parse()

	ctx := context.Background()

	kexinClient := impl.NewKexinSearchRPC()
	searchRes, err := kexinClient.Search(ctx, text, 10, "wrtest-123456")

	fmt.Println(searchRes, err)
}
