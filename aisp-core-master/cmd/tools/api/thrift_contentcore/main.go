package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/thrift_ai_tab"
)

// go run cmd/tools/api/thrift_contentcore/main.go
func main() {
	ctx := context.Background()
	service := thrift_ai_tab.NewAispCrawlerWebpageService()
	result, err := service.BatchGetContentWithFieldsByIdsAngleless(ctx, &content.BatchGetContentWithFieldsByIdsAnglelessParam{
		BizCode:   "AISP_CORE",
		SceneCode: "AISP_CORE",
		ObjectInfos: []*base.OutIDTypePair{
			{
				OutID: "4363047064463148618",
				Type:  content_core_thrift.ContentTypeCrawlerWebpage,
			},
			{
				OutID: "28941447131569501",
				Type:  content_core_thrift.ContentTypeCrawlerWebpage,
			},
		},
	})
	fmt.Println(util.GetJSONIgnoreError(result), err)
}
