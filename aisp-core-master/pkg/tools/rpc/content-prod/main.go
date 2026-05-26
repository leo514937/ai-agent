package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

func main() {

	rpcImpl := impl.NewContentProdRPCImpl()

	urls := []string{
		"https://www.zhihu.com/answer/3412835570",
		"https://www.zhihu.com/question/599935979/answer/3412835570",
		"https://zhuanlan.zhihu.com/p/403862960",
		"https://www.opsli.com",
	}
	res := rpcImpl.BatchCurlContentByUrl(context.Background(), urls)

	fmt.Println(util.GetJSONIgnoreError(res))

	fmt.Println("------------------")

	for _, v := range res {

		// 清洗 content 里的 html
		hasEquation := util.ContentHasEquation(v.GetContent())
		if !hasEquation {
			filteredBody, err := util.ContentFilterHtml(context.Background(), v.GetContent())
			if err == nil {
				fmt.Printf("输出清理后结果 URL: %s, Body:%s \n", v.GetURL(), filteredBody)
			}
		}
	}
}
