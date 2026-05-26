package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

// go run pkg/tools/rpc/tag_core/main.go
func main() {
	ctx := context.Background()
	docId := flag.Int64("id", 147330520, "contentId")
	contentType := flag.Int64("type", 2, "contentType")
	flag.Parse()

	docType := content.DocType_Type(*contentType)

	contents := []model.Content{model.NewContentWithDocType(*docId, docType)}
	tagResult := impl.DefaultTagGrpcImpl.BatchGetTag(ctx, rpc.SceneCode_AiUserInterest, rpc.AppGroupCode_AiUserRecall, contents)

	fmt.Println(tagResult)
}
