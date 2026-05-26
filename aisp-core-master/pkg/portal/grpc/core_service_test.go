package grpc

import (
	"context"
	"fmt"
	"testing"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	"git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/content"
)

const host = "localhost:9999"

func TestAISPCoreService_KnowledgeBaseDocDetail(t *testing.T) {
	request := &content.KnowledgeBaseDocDetailRequest{
		DocUniqueID: "bb844ab2-e472-4894-9709-6ef6f1a4dd6a",
	}

	ctx := context.Background()

	chatService := content.NewChatServiceClient(
		tzone.NewClient(
			"ChatService",
			tzone.Timeout(600*time.Millisecond),
			tzone.HostPort("localhost", "9999"),
			tzone.TargetName("aisp-core-thrift-service"),
		))

	response, err := chatService.KnowledgeBaseDocDetail(ctx, request)
	if err != nil {
		fmt.Printf("error: %v", err)
	}

	fmt.Printf("doc detail response: %v", response)
}

func TestAISPCoreService_KnowledgeBaseDocRetrieve(t *testing.T) {
	request := &content.KnowledgeBaseDocRetrieveRequest{
		DocUniqueID: "bb844ab2-e472-4894-9709-6ef6f1a4dd6a",
		Query:       "蛋白",
		TopK:        10,
	}

	ctx := context.Background()
	chatService := content.NewChatServiceClient(
		tzone.NewClient(
			"ChatService",
			tzone.Timeout(600*time.Millisecond),
			tzone.HostPort("localhost", "9999"),
			tzone.TargetName("aisp-core-thrift-service"),
		))

	response, err := chatService.KnowledgeBaseDocRetrieve(ctx, request)
	if err != nil {
		fmt.Printf("error: %v", err)
	}

	fmt.Printf("retrieve response: %v", response)
}
