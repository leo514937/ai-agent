package main

import (
	"context"
	"flag"
	"fmt"
	"math/rand"
	"sync"
	"sync/atomic"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/cmd/tools/api/grpc_service/request"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/spf13/cast"
)

type mainConfig struct {
	text          string
	host          string
	chatType      int
	buildType     int
	suggestType   int
	memberID      int64
	newSession    bool
	retryGen      bool
	chatStyle     int
	batchSize     int
	chatModel     int
	clientSource  int
	trafficSource int
	version       string
}

type Config struct {
	QPS         int
	Duration    time.Duration
	Concurrency int
}

func runQPSTest(cfg Config, config *mainConfig) {
	ctx, cancel := context.WithTimeout(context.Background(), cfg.Duration)
	defer cancel()

	var wg sync.WaitGroup
	var totalRequests int64
	startTime := time.Now()

	// 创建一个带缓冲的通道来控制并发
	semaphore := make(chan struct{}, cfg.Concurrency)

	// 计算每个请求之间的间隔
	interval := time.Second / time.Duration(cfg.QPS)

	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			wg.Wait()
			duration := time.Since(startTime)
			actualQPS := float64(totalRequests) / duration.Seconds()
			fmt.Printf("Test completed. Duration: %v, Total Requests: %d, Actual QPS: %.2f\n",
				duration.Round(time.Millisecond), totalRequests, actualQPS)
			return
		case <-ticker.C:
			wg.Add(1)
			go func() {
				defer wg.Done()
				semaphore <- struct{}{}        // 获取信号量
				defer func() { <-semaphore }() // 释放信号量

				// 模拟请求处理
				doRun(config)
				atomic.AddInt64(&totalRequests, 1)
			}()
		}
	}
}

func main() {
	cfg := Config{
		QPS:         2,               // 目标 QPS
		Duration:    1 * time.Minute, // 持续时间
		Concurrency: 3,               // 最大并发数
	}

	config := mainConfig{}
	flag.StringVar(&config.text, "text", "hello world", "user input query")
	flag.StringVar(&config.host, "host", "localhost:9999", "host name")
	flag.IntVar(&config.chatType, "chat_type", 8, "chatType")
	flag.IntVar(&config.buildType, "build_type", 1, "buildType")
	flag.IntVar(&config.suggestType, "suggest_type", 4, "suggestType")
	flag.IntVar(&config.chatStyle, "chat_style", 0, "0: 默认，1：深入，2：精简")
	flag.Int64Var(&config.memberID, "member_id", 13333333333, "member id")
	flag.BoolVar(&config.newSession, "new_session", false, "create new session")
	flag.BoolVar(&config.retryGen, "retry_gen", false, "is retry generate")
	flag.IntVar(&config.batchSize, "batch_size", 1, "协程批次")
	flag.IntVar(&config.chatModel, "model", 1, "选择模型 0: 通用模型 1: deepseek r1  2: qwq32b")
	flag.IntVar(&config.clientSource, "client_source", 0, "客户端来源 0未知 1WEB ...")
	flag.IntVar(&config.trafficSource, "traffic_source", 0, "流量来源 0未知 1直答 2搜索 ...")
	flag.StringVar(&config.version, "version", "v2", "直答版本")
	flag.Parse()

	fmt.Printf("Starting QPS test with target QPS: %d, Duration: %v, Max Concurrency: %d\n",
		cfg.QPS, cfg.Duration, cfg.Concurrency)
	runQPSTest(cfg, &config)
}

func doRun(config *mainConfig) {

	sessionID := "13333333333"
	if config.newSession {
		sessionID = cast.ToString(rand.Int63())
	}

	var messageGroupId int64
	if config.retryGen {
		messageGroupId = 7040890682733337321
	}
	extraInfo := &proto.ExtraInfo{
		DocQaExtraInfo: &proto.DocQaExtraInfo{
			DocId:       662342798,
			ContentType: "ANSWER",
			Paragraphs: []*proto.DocQaExtraParagraphInfo{
				{
					ParagraphIndex:   3,
					ParagraphVersion: "",
				},
				{
					ParagraphIndex:   4,
					ParagraphVersion: "",
				},
			},
		},
	}

	txn, ctx := log.StartTransaction("tools_api_grpc_service")
	defer txn.End(ctx)

	//// 创建 Session
	//sessionRequest := request.NewCreateSessionRequest(host, proto.ChatType(chatType), memberID, &proto.ExtraInfo{
	//	ShareSessionId:    3603656719371959213,
	//	ShareEndMessageId: 7380289014434286102,
	//})
	//sessionRequest.DoCreateSessionRequest(ctx)
	// 分别从两个rum 表中获取引导词
	wg := safe_group.NewGroup("runCase")
	for i := 0; i < config.batchSize; i++ {
		wg.Go(func() error {
			// 模拟发起 StreamChat 请求
			chatRequest := request.NewStreamChatRequest(
				config.host, config.text, proto.ChatType(config.chatType), sessionID, config.memberID,
				proto.ChatStyle(config.chatStyle), proto.ClientSource(config.clientSource), proto.TrafficSource(config.trafficSource), &proto.DocAboutQueriesRequest{
					DocId:   682269507,
					DocType: proto.DocType_ANSWER,
				})

			var knowledgeBases = []proto.KnowledgeBaseType{
				//proto.KnowledgeBaseType_KBT_GLOBAL,
				//proto.KnowledgeBaseType_KBT_ZHIHU,
				//proto.KnowledgeBaseType_KBT_PAPER,
				//proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE,
			}

			var currMounts = []*proto.ReferenceMount{}
			var hisMounts = []*proto.ReferenceMount{}

			//var assignmentDocs = []*proto.ChatCardProRelevantSource{
			//{
			//	DocId:   "222842404",
			//	DocType: proto.DocType_ARTICLE,
			//},
			//{
			//	DocId:   "1827028919834042368",
			//	DocType: proto.DocType_PAPER,
			//},
			//{
			//	DocId:   "1827028920802926592",
			//	DocType: proto.DocType_ZHI_DA_USER_UPLOAD,
			//},
			//}

			recallContentIds := []string{}

			//recallContentIds := []string{"1111", "22222"}
			chatRequest.DoStreamChat(ctx, messageGroupId, 0, 0,
				knowledgeBases, currMounts, hisMounts, nil, proto.ChatModel(config.chatModel), config.version, recallContentIds)

			// 模拟发起 DigitalAuthor 请求
			//digitalAuthorChatRequest := request.NewDigitalAuthorChatRequest(host, text)
			//digitalAuthorChatRequest.DoDigitalAuthorChat()

			// // 模拟发起 QueryMerge 请求
			// queryMergeRequest := request.NewQueryMergeRequest(host, text, proto.BuildQueryType(buildType), sessionID, memberID)
			// queryMergeRequest.DoQueryMergeRequest()

			// // 模拟发起 词推荐 请求
			suggestQueriesRequest := request.NewSuggestQueriesRequest(
				config.host, config.text, proto.SuggestQueriesType(config.suggestType), sessionID, "", config.memberID, extraInfo,
				proto.ClientSource(config.clientSource), proto.TrafficSource(config.trafficSource),
				&proto.DocAboutQueriesRequest{
					DocId:   682269507,
					DocType: proto.DocType_ANSWER,
				},
				[]*proto.DocAboutQueriesRequest{
					{
						DocId:   1829975511776026624,
						DocType: proto.DocType_PAPER,
					},
				},
			)
			suggestQueriesRequest.DoSuggestQueriesRequest()
			return nil
		})
	}
	_ = wg.Wait()
}
