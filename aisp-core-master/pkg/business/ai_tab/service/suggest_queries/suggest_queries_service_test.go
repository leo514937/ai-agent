package suggest_queries

import (
	"context"
	"testing"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
)

func TestSuggestQueries(t *testing.T) {
	var req = proto.SuggestQueriesRequest{
		Type: proto.SuggestQueriesType_AI_TAB_RELATED,
		Info: &proto.RequestInfo{
			SessionId: "111",
			MemberId:  1112222,
			Message: &proto.ChatMessage{
				MessageId:   "123",
				TimestampMs: time.Now().UnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        "HelloGrpcByZhihu",
			},
		},
	}
	//req.
	toProto, err := SuggestQueriesToProto(context.TODO(), &req)
	if err != nil {
		t.Errorf("输出 TestSuggestQueries 异常结果 %v", err)
		return
	}
	t.Logf("输出 TestSuggestQueries 测试结果 %v", toProto.String())
}
