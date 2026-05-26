package main

import (
	"context"
	"flag"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	dd "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
)

func main() {

	var (
		text        string
		source      string
		suggestType int
	)
	flag.StringVar(&text, "text", "你是谁啊？", "user input query")
	flag.StringVar(&text, "source", "你是谁", "user input source query")
	flag.IntVar(&suggestType, "suggest_type", 5, "suggestType")
	flag.Parse()

	ctx := context.Background()
	dao := impl.NewPrefabWordDao()

	word := dd.PrefabWord{
		AiQuestion:     text,
		SourceQuestion: source,
	}

	// 保存词到 redis
	err := dao.SavePrefabWordToRedisSet(ctx, proto.QueryType(suggestType), &word)
	if err != nil {
		fmt.Println(err)
	} else {
		fmt.Println("保存成功")
	}

	fmt.Println("----------------------")
	fmt.Println("输出随机词")
	// 从 redis 获取随机词
	res := dao.GetRandomPrefabWordByRedis(ctx, 50)
	for _, v := range res {
		fmt.Println(v)
	}

	// 删除测试数据
	_ = dao.RemovePrefabWordRedis(ctx, proto.QueryType(suggestType), &word)
}

func getRedisKey(key string, queryType proto.QueryType) string {
	return fmt.Sprintf("%s:%s", key, queryType.String())
}
