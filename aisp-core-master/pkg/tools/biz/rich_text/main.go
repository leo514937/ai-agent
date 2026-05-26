package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

func main() {
	ctx := context.Background()
	filteredBody, err := util.ContentFilterHtml(ctx, " <p>@朋友圈投放1分 12333 @阿诬123 <a href=\"http://local.zhihu.com:3003\">http://local.zhihu.com:3003</a> 44444</p><p>23322444</p>")
	fmt.Println(filteredBody, err)
}
