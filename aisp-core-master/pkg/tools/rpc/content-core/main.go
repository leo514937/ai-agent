package main

import (
	"context"
	"flag"
	"fmt"
	"strings"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

// go run pkg/tools/rpc/content-core/main.go
func main() {
	ctx := context.Background()
	outId := flag.Int64("id", 1827715257566687232, "contentId")
	//outId := flag.Int64("id", 1002300006890352412, "contentId") // 用户上传内容id样例
	contentId := flag.String("content_id", "1002200006203417464", "contentId")
	contentType := flag.Int64("type", 650, "contentId")
	arxivIds := flag.String("arxiv_ids", "2307.02288,2303.02271,2304.04616", "arxivIds")
	flag.Parse()

	// 2408.00026

	docType := content.DocType_Type(*contentType)

	contents := []model.Content{model.NewContentWithDocType(*outId, docType)}
	response := impl.DefaultContentCoreRPCImpl.BatchGetContent(ctx, contents, base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody,
		base.ContentInfoFieldContentBizExtDetail,
		base.ContentInfoFieldContentBizExt,
		base.ContentInfoFieldContentMediaDetail,
		base.ContentInfoFieldContentSummary)
	for k, v := range response {
		fmt.Println(fmt.Sprintf("content:%s,meta:%s", util.GetJSONIgnoreError(k), util.GetJSONIgnoreError(v)))
	}

	fmt.Println("Token =========================")
	contentTokens := []model.Content{model.NewContentWithToken("3412835570", "ANSWER")}
	response1 := impl.DefaultContentCoreRPCImpl.BatchGetContent(ctx, contentTokens, base.ContentInfoFieldContentDetail, base.ContentInfoFieldContentBody)
	for k, v := range response1 {
		fmt.Println(fmt.Sprintf("content:%s,meta:%s", util.GetJSONIgnoreError(k), util.GetJSONIgnoreError(v)))
	}

	fmt.Println("统一id =========================")
	response2 := impl.DefaultContentCoreRPCImpl.BatchGetContentByContentID(ctx, []string{*contentId}, base.ContentInfoFieldContentDetail, base.ContentInfoFieldContentBody, base.ContentInfoFieldContentBizExtDetail)
	for k, v := range response2 {
		fmt.Println(fmt.Sprintf("content:%s,meta:%s", util.GetJSONIgnoreError(k), util.GetJSONIgnoreError(v)))
	}

	fmt.Println("批量站外信息转站内paper =========================")
	outSitePaperArr := make([]rpc.OutSitePaper, 0)
	for _, arxivId := range strings.Split(*arxivIds, ",") {
		outSitePaperArr = append(outSitePaperArr, rpc.OutSitePaper{OutId: arxivId, PaperType: rpc.OutSitePaperTypeArxiv})
	}
	response3 := impl.DefaultContentCoreRPCImpl.BatchGetContentPaperByOutSiteTypeId(ctx, outSitePaperArr)
	for k, v := range response3 {
		fmt.Println(fmt.Sprintf("outsite:%s, content:%s", util.GetJSONIgnoreError(k), util.GetJSONIgnoreError(v)))
	}
}
