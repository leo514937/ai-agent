package main

import (
	"context"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {
	ctx := context.Background()

	contentServiceClient := content.NewContentServiceClient(
		tzone.NewClient(
			"ContentService",
			tzone.Timeout(600*time.Millisecond),
			tzone.HostPort("localhost", "9999"),
		))

	param := &content.BatchGetContentWithFieldsByIdsAnglelessParam{
		ObjectInfos: []*base.OutIDTypePair{
			{
				OutID: "63856735559936",
				Type:  "CrawlerWebpage",
			},
			{
				OutID: "5375335940830976",
				Type:  "CrawlerWebpage",
			},
		},
	}
	resp, err := contentServiceClient.BatchGetContentWithFieldsByIdsAngleless(ctx, param)
	if err != nil {
		log.Errorf(ctx, "batch get crawler webpage err: %+v", err)
		return
	}

	log.Infof(ctx, "resp: %+v", resp)
}
