package main

import (
	"context"
	"errors"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	conf2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"github.com/google/uuid"
)

func main() {

	bizRequestContext := genBizRequestContext()
	itemList, _, _, err := graph.RunGraph(context.Background(), bizRequestContext, nil)
	if err != nil && len(itemList) == 0 {
		err = errors.New("empty response")
	}
	res := itemList[0]
	fmt.Printf("res: %s err: %+v\n", util.GetJSONIgnoreError(res), err)
}

func genBizRequestContext() *entities.RequestContext {
	resources.Init(graph_constant.ApiStreamChat)

	// 获取当前图配置
	graphLogicConfig, _ := conf2.GetGraphConfig(conf2.LogicConfigNameByQueryMerge)

	return entities.NewRequestContextFromBuildQueryRequest(&proto.BuildQueryRequest{
		Info: &proto.RequestInfo{
			SessionId: "",
			Message: &proto.ChatMessage{
				MessageId:   uuid.New().String(),
				TimestampMs: util.TimeUnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        "你好",
			},
			MemberId: 1,
		},
		Type: proto.BuildQueryType_SEARCH_TAB_SEARCH_CARD,
	}, graphLogicConfig.GetBizConfigMap())
}
