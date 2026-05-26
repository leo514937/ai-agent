package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

// go run pkg/tools/rpc/content-regulate/main.go
func main() {
	ctx := context.Background()
	kmContentId := flag.Int64("km_id", 642320564, "会员contentId")
	kmContentType := flag.Int64("km_type", 2, "会员contentType")
	contentId := flag.Int64("id", 631331688, "contentId")
	contentType := flag.Int64("type", 2, "contentType")
	flag.Parse()

	contents := []model.Content{{
		ContentID:   *kmContentId,
		ContentType: content.DocType_Type(*kmContentType),
	}, {
		ContentID:   *contentId,
		ContentType: content.DocType_Type(*contentType),
	}}

	response := impl.DefaultContentRegulateRPCImpl.BatchGetValidInstruction(ctx, rpc.SceneCodeRAI, rpc.SubSceneCodeDEFAULT, contents)
	for k, v := range response {
		fmt.Println(fmt.Sprintf("content:%s,res:%s", util.GetJSONIgnoreError(k), util.GetJSONIgnoreError(v)))
	}
}
