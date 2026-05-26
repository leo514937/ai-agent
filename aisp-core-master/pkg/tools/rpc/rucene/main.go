package main

import (
	"context"
	"flag"
	"fmt"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/graph/conf"
	ai_daily_model "git.in.zhihu.com/zhihu/aisp-core/pkg/business/ai_daily/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

func buildIndex(ctx context.Context, ruceneClient rpc.RuceneServiceRPC) {
	err := ruceneClient.BuildNewIndex(ctx, model.PublicKnowledgeBasePath, model.PublicKnowledgeBaseIndex, model.PublicKnowledgeBaseMapping, model.PublicKnowledgeBaseSetting)
	fmt.Println(fmt.Sprintf("build index err:%v", err))
}

func openIndex(ctx context.Context, ruceneClient rpc.RuceneServiceRPC) {
	err := ruceneClient.OpenLogIndex(ctx, model.PersonalKnowledgeDocPath, model.PersonalKnowledgeDocIndex)
	fmt.Println(fmt.Sprintf("open index err:%v", err))
}

func buildAiDailyIndex(ctx context.Context, ruceneClient rpc.RuceneServiceRPC) {
	err := ruceneClient.BuildNewIndex(ctx, conf.RucenePath, conf.RuceneIndex, model.AIDailyMappings, model.AIDailySettings)
	fmt.Println(fmt.Sprintf("buildAiDailyIndex err:%v", err))
}

func deleteAiDailyIndex(ctx context.Context, ruceneClient rpc.RuceneServiceRPC, id string) {
	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)
	err := ruceneClient.Delete(ctx, ruceneHost, conf.RucenePath, conf.RuceneIndex, &ai_daily_model.RuceneDoc{DocId: id}, "")
	fmt.Println(fmt.Sprintf("deleteAiDailyIndex err:%v", err))
}

func add(ctx context.Context, ruceneClient rpc.RuceneServiceRPC) {
	doc := model.LogRucene{
		Id:            "stream_chat.DISCOVER_TAB-6585-346789",
		MemberId:      17223006,
		Scene:         "DISCOVER_TAB",
		GraphName:     "stream_chat.DISCOVER_TAB",
		SessionId:     "87654",
		RequestTimeMs: 456780,
		MessageId:     "7890",
		Query:         "你好世界",
		QuerySeg: model.SegmentInfo{
			Words: []*model.Word{
				{Value: "你好", Begin: 0, Length: 2},
				{Value: "世界", Begin: 2, Length: 4},
			},
			Raw:   "你好世界",
			Store: true,
		},
		ResponseTimeMs: 0,
		RespMessageId:  "123456543",
		Response:       []string{"高考如何报"},
		ResponseSeg: model.SegmentInfo{
			Words: []*model.Word{
				{Value: "高考", Begin: 0, Length: 2},
				{Value: "如何", Begin: 2, Length: 4},
				{Value: "报", Begin: 4, Length: 1},
			},
			Raw:   "高考如何报",
			Store: true,
		},
		Security: []string{},
		AuthorId: 0,
		TraceId:  "Guiafe876",
	}

	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)

	err := ruceneClient.Add(ctx, ruceneHost, model.Path, model.Index, doc, "")
	fmt.Println(fmt.Sprintf("add doc err:%v", err))
}

func addSparse(ctx context.Context, ruceneClient rpc.RuceneServiceRPC) {
	doc := model.CrawlerWebpageRucene{
		Id:      "1234567890",
		DocId:   1234567890,
		DocType: "CrawlerWebpage",
		Domain:  "医学",
		Extra:   "",
		SparseScore: []*model.SparseWord{
			{Word: "2024", Score: 0.13},
			{Word: "LLM", Score: 0.54},
		},
	}

	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)

	err := ruceneClient.Add(ctx, ruceneHost, model.CrawlerWebpagePath, model.CrawlerWebpageIndex, doc, "")
	fmt.Println(fmt.Sprintf("add doc err:%v", err))
}

// 新索引执行下面两行命令：
// 1、 go run pkg/tools/rpc/rucene/main.go -method=build_index
// 2、 go run pkg/tools/rpc/rucene/main.go -method=open_index
func main() {
	ctx := context.Background()
	method := flag.String("method", "search", "search/upsert/delete/infos")
	id := flag.String("id", "", "rucene_doc_id")
	flag.Parse()

	ruceneClient := rpc.DefaultRuceneServiceRPC

	switch *method {
	case "build_index":
		buildIndex(ctx, ruceneClient)
	case "build_ai_daily_index":
		buildAiDailyIndex(ctx, ruceneClient)
	case "delete_ai_daily_index":
		deleteAiDailyIndex(ctx, ruceneClient, *id)
	case "open_index":
		openIndex(ctx, ruceneClient)
	case "add":
		add(ctx, ruceneClient)
	case "addSparse":
		addSparse(ctx, ruceneClient)
	}
}
