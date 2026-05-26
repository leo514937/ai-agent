package main

import (
	"context"
	"flag"
	"fmt"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
)

// go run main.go -alias 肾6
func main() {
	var alias string
	flag.StringVar(&alias, "alias", "肾6,iphone6", "alias")
	flag.Parse()
	ctx := context.Background()

	skuDao := impl.NewZhiDaSkuDao()

	// 无需再判断 value = 0(表示无该数据)，方法内部已做过滤
	// 返回结果为map key=alias, value=link_card_id
	res := skuDao.GetSkuLinkCardIds(ctx, strings.Split(alias, ","))
	fmt.Printf("输出直答商品数据 数据结果 => %v\n", res)
}
