package main

import (
	"context"
	"flag"
	"fmt"
	"strings"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	chat_content_thrift "git.in.zhihu.com/one-rpc-go/thrift-chat_content/chat_content_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/cmd/tools/api/rpc_service/search_res_notice/request"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

func main() {
	ctx := context.Background()
	log.Infof(ctx, "准备处理")

	var (
		query    string
		memberId int64
	)
	flag.StringVar(&query, "query", "蓝牙耳机", "用户Query")
	flag.Int64Var(&memberId, "member_id", 246248568, "用户ID")
	flag.Parse()

	resources.Init(graph_constant.ApiStreamChat)

	newClient := request.NewClient()
	newClient.DoServiceResultNotice(ctx, &chat_content_thrift.SearchResultNoticeRequest{
		Query:    query,
		MemberId: memberId,
		RecallContentList: []*chat_content_thrift.Content{
			{
				DocId:   682269507,
				DocType: "ANSWER",
			},
		},
	})

	// 获取当前图配置
	req := &proto.SuggestQueriesRequest{
		Type: proto.SuggestQueriesType_SEARCH_ASK_AGAIN_RELATED,
		Header: &proto.RequestHeader{
			ClientSource:  proto.ClientSource_UNDEFINED_SOURCE,
			TrafficSource: proto.TrafficSource_undefined_traffic,
		},
		Info: &proto.RequestInfo{
			SessionId: "",
			Message: &proto.ChatMessage{
				MessageId:   "",
				TimestampMs: 0,
				Type:        proto.ChatMessageType_TEXT,
				Text:        query,
			},
			MemberId: memberId,
		},
	}
	graphLogicConfig, _ := conf.GetGraphConfig(conf.LogicConfigNameByQueriesSearchAsk)
	fmt.Printf("图配置日志：%s \n", util.GetJSONIgnoreError(graphLogicConfig.GetBizConfigMap()))

	bizRequestContext := entities.NewRequestContextFromSuggestQueriesRequest(req, graphLogicConfig.GetBizConfigMap(), false)
	itemList, _, _, graphErr := graph.RunGraph(ctx, bizRequestContext, nil)
	if graphErr != nil {
		log.Errorf(ctx, "run graph failed => SuggestQueries: %v", graphErr)
	}

	queries := make([]*proto.Query, 0)
	for _, item := range itemList {
		queryPoint := &proto.Query{
			Id:        item.QueryId,
			Query:     item.Text,
			QueryType: item.QueryType,
			RiskType:  strings.ToLower(item.QueryCensorType),
		}
		queries = append(queries, queryPoint)
	}
	fmt.Printf("图执行结果：%s \n", util.GetJSONIgnoreError(queries))
}
