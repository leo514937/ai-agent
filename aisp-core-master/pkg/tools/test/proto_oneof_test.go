package test

import (
	"testing"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

func TestSuggestQueries(t *testing.T) {

	response := &proto.ChatResponse{
		State: proto.ChatState_PROCESSING,
		Message: &proto.ChatMessage{
			MessageId:   "123213",
			TimestampMs: time.Now().UnixMicro(),
			Type:        proto.ChatMessageType_TEXT,
			Text:        "hello",
		},
		RelevantQueries: []*proto.Query{
			{
				Id:        "123",
				QueryType: proto.QueryType_RELATE_WORD,
				RiskType:  "123213",
				Query:     "你知道知乎吗",
			},
		},
		Cards: []*proto.ChatCard{
			{
				CardContent: &proto.ChatCard_ZhihuRelevantSource{
					ZhihuRelevantSource: &proto.ChatCardZhihuRelevantSource{
						DocId:   123213,
						DocType: "QUESTION",
					},
				},
			},
			{
				CardContent: &proto.ChatCard_ZhihuRelevantSource{
					ZhihuRelevantSource: &proto.ChatCardZhihuRelevantSource{
						DocId:   123213,
						DocType: "QUESTION",
					},
				},
			},
			{
				CardContent: &proto.ChatCard_OtherRelevantSource{
					OtherRelevantSource: &proto.ChatCardOtherRelevantSource{
						DocTitle: "知乎在2024年的年会",
						DocUrl:   "https://www.zhihu.com/answer/123213213",
					},
				},
			},
		},
	}

	card := response.GetCards()[2]
	// 检查 oneof 字段类型
	switch x := card.GetCardContent().(type) {
	case *proto.ChatCard_ZhihuRelevantSource:
		t.Logf("输出原始 oneof res (zhihu) => %v", util.GetJSONIgnoreError(x.ZhihuRelevantSource))
	case *proto.ChatCard_OtherRelevantSource:
		t.Logf("输出原始 oneof res (other) => %v", util.GetJSONIgnoreError(x.OtherRelevantSource))
	default:
		t.Error("Unknown type")
	}
	t.Logf("输出原始 resp => %v", util.GetJSONIgnoreError(response))
}
