package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

// go run pkg/tools/rpc/aisp-tools/main.go
func main() {
	ctx := context.Background()
	//ossUrl := flag.String("url", "https://manager-lsy.oss-cn-beijing.aliyuncs.com/push-over%E6%96%B9%E6%B3%95%E4%B8%AD%E4%B8%80%E7%A7%8D%E8%80%83%E8%99%91%E9%AB%98%E9%98%B6%E6%8C%AF%E5%9E%8B%E5%BD%B1%E5%93%8D%E7%9A%84%E6%B0%B4%E5%B9%B3%E8%8D%B7%E8%BD%BD%E5%88%86%E5%B8%83%E6%A8%A1%E5%BC%8F.pdf", "oss url")
	//flag.Parse()

	//pdfBytes, _ := impl.DefaultOssImpl.GetFileBytes(ctx, *ossUrl)
	//
	//parseResponse, err := impl.DefaultAispToolsClient.ParsePdf(ctx, rpc.ProcessorNamePymuPdfParser, pdfBytes)
	//fmt.Println(fmt.Sprintf("pdf parse result:%v, err:%v", util.GetJSONIgnoreError(parseResponse), err))

	doc := model.NewContentWithDocType(247593877, content.DocType_Article)
	contents := []model.Content{doc}
	response := impl.DefaultContentCoreRPCImpl.BatchGetContent(ctx, contents, base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentExtInfo,
		base.ContentInfoFieldContentBody,
		base.ContentInfoFieldContentBizExtDetail,
		base.ContentInfoFieldContentBizExt,
		base.ContentInfoFieldContentMediaDetail,
		base.ContentInfoFieldContentSummary)
	body := response[doc].GetContentBody().GetBody()

	parseResponse2, err := impl.DefaultAispToolsClient.ParseHtml(ctx, rpc.ProcessorNameLocalHtmlParser, []byte(body), "test", "")
	fmt.Println(fmt.Sprintf("html parse result:%v, err:%v", util.GetJSONIgnoreError(parseResponse2), err))

}
