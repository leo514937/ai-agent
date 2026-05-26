package main

import (
	"context"
	"flag"
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/discover_tab/service"
)

func main() {
	var (
		text     string
		chatType int
	)
	flag.StringVar(&text, "text", "hello world", "user input query")
	flag.IntVar(&chatType, "chat_type", 11, "chatType")
	flag.Parse()
	queries := strings.Split(text, ",")
	ctx := context.TODO()
	for _, query := range queries {
		service.DoClearZhidaCache(ctx, proto.ChatType(chatType), query)
	}
}
