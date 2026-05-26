package main

import (
	"context"
	"flag"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/cmd/tools/api/grpc_service/request"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/spf13/cast"
	"google.golang.org/protobuf/types/known/wrapperspb"
)

// 启动命令：
// server 端：make all;./bin/grpc-service
// client 端：go run cmd/tools/api/grpc_service/main.go
func main() {
	var (
		text      string
		host      string
		chatType  int
		memberID  int64
		batchSize int
		chatModel int
		version   string
	)
	flag.StringVar(&text, "text", "hello world", "user input query")
	flag.StringVar(&host, "host", "localhost:9999", "host name")
	flag.IntVar(&chatType, "chat_type", 11, "chatType")
	flag.Int64Var(&memberID, "member_id", 158113101041, "member id")
	flag.IntVar(&batchSize, "batch_size", 1, "协程批次")
	flag.IntVar(&chatModel, "model", 1, "选择模型 0: 通用模型 1: deepseek r1  2: qwq32b")
	flag.StringVar(&version, "version", "v2", "直答版本")
	flag.Parse()

	txn, ctx := log.StartTransaction("tools_api_grpc_service")
	defer txn.End(ctx)

	iDGenerator := dao.NewIDGenerator()

	sessionID := request.NewCreateSessionRequest(host, proto.ChatType(chatType), memberID, nil,
		getHistory(ctx, iDGenerator, 10)).
		DoCreateSessionRequest(ctx)

	queryMessageId, _ := iDGenerator.GenerateIDByType(ctx, dao.GeneratorIdTypeMessageId)
	answerMessageId, _ := iDGenerator.GenerateIDByType(ctx, dao.GeneratorIdTypeMessageId)

	// 分别从两个rum 表中获取引导词
	wg := safe_group.NewGroup("runCase")
	for i := 0; i < batchSize; i++ {
		wg.Go(func() error {
			// 模拟发起 StreamChat 请求
			chatRequest := request.NewStreamChatRequest(
				host, text, proto.ChatType(chatType), sessionID, memberID,
				proto.ChatStyle_THOROUGH, proto.ClientSource_PC_WEB, proto.TrafficSource_zhida_gr_demo,
				&proto.DocAboutQueriesRequest{
					DocId:   681680326,
					DocType: proto.DocType_ANSWER,
				})

			var knowledgeBases = []proto.KnowledgeBaseType{
				//proto.KnowledgeBaseType_KBT_GLOBAL,
				//proto.KnowledgeBaseType_KBT_ZHIHU,
				//proto.KnowledgeBaseType_KBT_PAPER,
				//proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE,
			}

			recallContentIds := []string{}

			var currMounts = []*proto.ReferenceMount{}
			var hisMounts = []*proto.ReferenceMount{}
			// 指定模型参数
			var modelArgs = &proto.ModelArgs{
				MaxTokens:   wrapperspb.Int32(1024),
				Temperature: wrapperspb.Float(0.9),
			}
			chatRequest.DoStreamChat(ctx, queryMessageId, queryMessageId, answerMessageId,
				knowledgeBases, currMounts, hisMounts, modelArgs, proto.ChatModel(chatModel), version, recallContentIds)
			return nil
		})
	}
	_ = wg.Wait()
}

func getHistory(ctx context.Context, idGenerator dao.IDGenerator, n int) []*proto.DialogMessageWrapper {
	messages := make([]*proto.DialogMessageWrapper, 0)
	qBase := "你是谁"
	aBase := "我是机器人"
	for i := 1; i <= n; i++ {
		queryId, queryErr := idGenerator.GenerateIDByType(ctx, dao.GeneratorIdTypeMessageId)
		if queryErr != nil {
			continue
		}
		answerId, answerErr := idGenerator.GenerateIDByType(ctx, dao.GeneratorIdTypeMessageId)
		if answerErr != nil {
			continue
		}
		query := fmt.Sprintf("%s-%d", qBase, i)
		answer := fmt.Sprintf("%s-%d", aBase, i)
		messages = append(messages, &proto.DialogMessageWrapper{
			Query: &proto.DialogMessage{
				MessageId: cast.ToString(queryId),
				Message:   query,
			},
			Answer: &proto.DialogMessage{
				MessageId: cast.ToString(answerId),
				Message:   answer,
			},
		})
	}
	return messages
}
