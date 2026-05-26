package main

import (
	"context"
	"errors"
	"flag"
	"fmt"

	baselog "git.in.zhihu.com/go/base/telemetry/log"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/google/uuid"
)

func main() {
	log.SetLevel(baselog.DebugLevel)
	var text string
	flag.StringVar(&text, "text", "hello world", "user input query")
	flag.Parse()

	bizRequestContext := genBizRequestContext(text)

	itemList, _, _, err := graph.RunGraph(context.Background(), bizRequestContext, nil)
	if err != nil && len(itemList) == 0 {
		err = errors.New("empty response")
	}
	res := itemList[0]
	fmt.Printf("res: %s err: %+v\n", util.GetJSONIgnoreError(res), err)
}

func genBizRequestContext(text string) *entities.RequestContext {
	resources.Init(graph_constant.ApiStreamChat)
	return entities.NewRequestContextFromChatRequestByBizType(&proto.ChatRequest{
		Info: &proto.RequestInfo{
			SessionId: "",
			Message: &proto.ChatMessage{
				MessageId:   uuid.New().String(),
				TimestampMs: util.TimeUnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        text,
			},
			MemberId: 1,
		},
		Type: proto.ChatType_DISCOVER_TAB,
	}, "test_kb_bing_recall")
}
