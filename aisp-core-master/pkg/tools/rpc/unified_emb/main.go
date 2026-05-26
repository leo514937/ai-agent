package main

import (
	"context"
	"flag"
	"fmt"
	"strings"

	"git.in.zhihu.com/pb-go/zai-proto/ai/common"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

// go run pkg/tools/rpc/unified_emb/main.go
func main() {
	ctx := context.Background()
	texts := flag.String("texts", "高考如何报志愿,计算机专业相关高校", "input texts")
	flag.Parse()
	textSlice := strings.Split(*texts, ",")

	klaraEmbResponse := impl.DefaultUnifiedEmbGrpcImpl.BatchGetTextKlaraEmbedding(ctx, textSlice, common.EmbeddingType_TextBge1024d)
	fmt.Println(fmt.Sprintf("klara embedding search result:%v", util.GetJSONIgnoreError(klaraEmbResponse)))

	EmbResponse := impl.DefaultUnifiedEmbGrpcImpl.GetEmbedding(ctx, textSlice[0], common.EmbeddingType_TextQueryMoco64d)
	fmt.Println(fmt.Sprintf("embedding search result:%v", util.GetJSONIgnoreError(EmbResponse)))
}
