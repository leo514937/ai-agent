package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/go/cafe/stream"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/consumer/process"
)

// go run pkg/tools/biz/kafka/main.go
func main() {
	ctx := context.Background()
	flag.Parse()

	msg := "{\"ZhidaRelevantSource\":{\"doc_id\":\"1827715257566687232\",\"doc_type\":7}}"
	//msg := "{\"ZhidaRelevantSource\":{\"doc_id\":\"1002300006331478815\",\"doc_type\":8}}"
	err := process.NewDocumentParsingProcessor().Process(ctx, &stream.Message{
		Value: []byte(msg),
	})

	fmt.Println(fmt.Sprintf("err:%v", err))
}
