package request

import (
	"context"
	"fmt"
	"time"

	"git.in.zhihu.com/go/base/tzone"
	chat_content_thrift "git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

func init() {
	DefChatServiceThriftRpcClient = NewClient()
}

var DefChatServiceThriftRpcClient *ChatServiceThriftRpcClient

func NewClient() *ChatServiceThriftRpcClient {
	return &ChatServiceThriftRpcClient{
		client: chat_content_thrift.NewChatServiceClient(tzone.NewClient(
			"ChatService",
			//tzone.HostPort("localhost", "9999"),
			tzone.TargetName("aisp-core-thrift-service"),
			tzone.Timeout(2*time.Second))),
	}
}

type ChatServiceThriftRpcClient struct {
	client *chat_content_thrift.ChatServiceClient
}

// DoServiceResultNotice 搜索结果通知
func (r *ChatServiceThriftRpcClient) DoServiceResultNotice(ctx context.Context, request *chat_content_thrift.SearchResultNoticeRequest) {
	info, err := r.client.SearchResultNotice(ctx, request)
	if err != nil {
		fmt.Println("Error DoGetCensorInfo => ", err)
		return
	}
	fmt.Println("输出 DoServiceResultNotice信息 => ", util.GetJSONIgnoreError(info))
}
