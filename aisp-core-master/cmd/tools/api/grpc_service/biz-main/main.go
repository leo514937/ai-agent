package main

import (
	"flag"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

// 启动命令：
// server 端：make all;./bin/grpc-service
// client 端：go run cmd/tools/api/grpc_service/biz-main/main.go
func main() {
	var (
		host          string
		text          string
		searchType    int
		buildType     int
		suggestType   int
		memberID      int64
		newSession    bool
		retryGen      bool
		chatStyle     int
		batchSize     int
		clientSource  int
		trafficSource int
	)
	flag.StringVar(&host, "host", "localhost:9999", "host name")
	flag.StringVar(&text, "text", "hello world", "user input query")
	flag.IntVar(&searchType, "search_type", 1, "搜索类型 1: 文档 2: 文件夹")
	flag.Int64Var(&memberID, "member_id", 246302179, "member id")
	flag.IntVar(&batchSize, "batch_size", 1, "协程批次")

	flag.IntVar(&buildType, "build_type", 1, "buildType")
	flag.IntVar(&suggestType, "suggest_type", 6, "suggestType")
	flag.IntVar(&chatStyle, "chat_style", 0, "0: 默认，1：深入，2：精简")
	flag.BoolVar(&newSession, "new_session", false, "create new session")
	flag.BoolVar(&retryGen, "retry_gen", false, "is retry generate")
	flag.IntVar(&clientSource, "client_source", 0, "客户端来源 0未知 1WEB ...")
	flag.IntVar(&trafficSource, "traffic_source", 0, "流量来源 0未知 1直答 2搜索 ...")
	flag.Parse()

	txn, ctx := log.StartTransaction("tools_api_grpc_biz_service")
	defer txn.End(ctx)

	// 分别从两个rum 表中获取引导词
	wg := safe_group.NewGroup("runCase")
	for i := 0; i < batchSize; i++ {
		wg.Go(func() error {
			//// 搜索召回接口
			//searchRequest := request.NewRecallSearchRequest(
			//	host,
			//	memberID,
			//	proto.KbRecallSearchType(searchType),
			//	[]proto.PersonalKnowledgeBaseType{proto.PersonalKnowledgeBaseType_PKB_RSS, proto.PersonalKnowledgeBaseType_PKB_FOLDER},
			//	[]proto.KbRecallSearchField{proto.KbRecallSearchField_RSF_TITLE},
			//)
			//searchRequest.DoRecallSearch(ctx, text)
			//
			//// 构建知识库索引接口
			//buildRequest := request.NewBuildKnowledgeBaseIndexRequest(
			//	host,
			//	memberID,
			//	11111111111111111,
			//	proto.DocType_EXTERNAL_WEBPAGE,
			//	11111111111111111,
			//	"test",
			//	proto.PersonalKnowledgeBaseType_PKB_FOLDER,
			//	proto.KbActionType_AT_INSERT,
			//)
			//buildRequest.DoBuildPersonalKnowledgeBaseIndex(ctx)

			return nil
		})
	}
	_ = wg.Wait()
}
