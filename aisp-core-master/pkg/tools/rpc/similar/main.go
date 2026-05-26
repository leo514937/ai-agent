package main

import (
	"context"
	"flag"
	"fmt"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

var greetWords = []string{
	"您好",
	"你好",
	"嗨",
	"Hello",
	"Hi",
	"早安",
	"午安",
	"晚安",
	"在么",
	"你是谁",
	"你叫什么名字",
	"你的名字是什么",
	"自我介绍",
	"介绍下你自己",
}

// go run pkg/tools/rpc/similar/main.go
func main() {

	var (
		texts string
		tag   string
	)

	flag.StringVar(&texts, "texts", "你好呀", "input texts")
	flag.StringVar(&tag, "tag", "数码", "member tag")
	flag.Parse()

	ctx := context.Background()
	grpcImpl := impl.DefaultSimilarGrpcImpl

	textSlice := strings.Split(texts, ",")
	var response []float64
	resp, err := grpcImpl.GetSimilarV2(ctx, textSlice, greetWords, rpc.SimilarSourceCodeV2Code)
	if err == nil && resp != nil {
		for _, item := range resp.GetItems() {
			response = append(response, item.GetScore())
		}
	}
	fmt.Println("测试 GetSimilarV2 接口")
	fmt.Println(fmt.Sprintf("get similar result:%v", util.GetJSONIgnoreError(response)))

	fmt.Println("测试 GetSearchV2 接口")
	searchV2Resp := grpcImpl.GetSearchV2(ctx, tag, rpc.SimilarSourceCodeInterestKeyword, 10)
	fmt.Println(fmt.Sprintf("get similar result:%v", util.GetJSONIgnoreError(searchV2Resp)))

}
