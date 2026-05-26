package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
)

func main() {
	client := impl.NewSerperHttpClient()

	res, err := client.Search(context.Background(), "二氢槲皮素", 10)
	if err != nil {
		fmt.Sprintf("error: %v", err)
	}
	println(res)
}
