package main

import (
	"context"
	"flag"
	"fmt"

	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/document_parse"
)

// go run pkg/tools/rpc/oss/main.go
func main() {
	ctx := context.Background()
	pdfPath := flag.String("path", "zhida/application/3344-241115/0fc8b077-a2fe-11ef-bdfc-8a197e176af8-cau.pdf", "")
	flag.Parse()

	fmt.Println(service.DefaultDocumentParseService.ConcurrentGetOssUrlFromPath(ctx, []string{*pdfPath}))
}
