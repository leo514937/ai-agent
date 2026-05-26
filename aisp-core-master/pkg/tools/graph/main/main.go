package main

import (
	"context"
	"flag"
	"fmt"
	"math/rand"

	baselog "git.in.zhihu.com/go/base/telemetry/log"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/google/uuid"
	"github.com/spf13/cast"
	grpc2 "google.golang.org/grpc"
)

// 启动命令eg: go run pkg/tools/graph/main/main.go -chatType 14 -clientSource 3 -trafficSource 17 -chatStyle 2 -memberId 123456789 -query 如何理解GSPO
func main() {
	chatType := flag.Int64("chatType", 14, "chatType")
	query := flag.String("query", "如何评价游戏《银色》？", "query text to ask")
	clientSource := flag.Int64("clientSource", 3, "clientSource (0:UNDEFINED_SOURCE, 1:PC_WEB, 2:MOBILE_WEB, 3:ZHIHU_APP)")
	trafficSource := flag.Int64("trafficSource", 31, "trafficSource (0:undefined_traffic, 1:zhida, 2:ai_search_card, 3:entity, ...)")
	// 公共可测试的用户ID 246302179 1342469863
	memberId := flag.Int64("memberId", 1342469863, "member ID")
	chatStyle := flag.Int64("chatStyle", 2, "chatStyle (0:UNDEFINED_STYLE, 1:THOROUGH, 2:SIMPLE, 3:DEEP_THINKING)")
	flag.Parse()
	chatTypeEnum := proto.ChatType(*chatType)
	clientSourceEnum := proto.ClientSource(*clientSource)
	trafficSourceEnum := proto.TrafficSource(*trafficSource)
	chatStyleEnum := proto.ChatStyle(*chatStyle)
	bizRequestContext := genBizRequestContext(chatTypeEnum, *query, clientSourceEnum, trafficSourceEnum, *memberId, chatStyleEnum)

	Execute(bizRequestContext)
}

type mockStreamChatServer struct {
	grpc2.ServerStream
}

func (m *mockStreamChatServer) Send(resp *proto.ChatResponse) error {
	// Mock send method
	return nil
}

func (m *mockStreamChatServer) Context() context.Context {
	return context.Background()
}

func Execute(req *proto.ChatRequest) (interface{}, *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], error) {
	log.SetLevel(baselog.DebugLevel)

	service := grpc.NewAispChatService()
	stream := &mockStreamChatServer{}

	err := service.StreamChat(req, stream)
	fmt.Println(fmt.Sprintf("err is : %v", err))
	return nil, nil, err
}

func genBizRequestContext(chatType proto.ChatType, query string, clientSource proto.ClientSource, trafficSource proto.TrafficSource, memberId int64, chatStyle proto.ChatStyle) *proto.ChatRequest {
	fmt.Println(fmt.Sprintf("chat type is : %s", chatType.String()))
	fmt.Println(fmt.Sprintf("query is : %s", query))
	fmt.Println(fmt.Sprintf("client source is : %s", clientSource.String()))
	fmt.Println(fmt.Sprintf("traffic source is : %s", trafficSource.String()))
	fmt.Println(fmt.Sprintf("chatStyle is : %s", chatStyle.String()))
	fmt.Println(fmt.Sprintf("member id is : %d", memberId))

	resources.Init(graph_constant.ApiStreamChat)
	request := &proto.ChatRequest{
		Type: chatType,
		Info: &proto.RequestInfo{
			SessionId: cast.ToString(rand.Int63()),
			Message: &proto.ChatMessage{
				MessageId:   util.Int64String(int64(uuid.New().ID())),
				TimestampMs: util.TimeUnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        query,
			},
			MemberId: memberId,
		},
		RespMessageId: util.Int64String(int64(uuid.New().ID())),
		Header: &proto.RequestHeader{
			ClientSource:  clientSource,
			TrafficSource: trafficSource,
			Version:       "v2",
		},
		ChatStyle:          chatStyle,
		CurrReferenceMount: []*proto.ReferenceMount{
			//{
			//	MountBase: &proto.PersonalKnowledgeBase{
			//		Visibility: proto.KnowledgeBaseVisibility_PUBLIC_FEATURE,
			//	},
			//},
			//{
			//	MountBase: &proto.PersonalKnowledgeBase{
			//		KnowledgeBaseId:   7474549483516594575,
			//		KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_RSS,
			//	},
			//},
		},
		KnowledgeBases: []proto.KnowledgeBaseType{
			proto.KnowledgeBaseType_KBT_GLOBAL,
			proto.KnowledgeBaseType_KBT_ZHIHU,
			proto.KnowledgeBaseType_KBT_PAPER,
			proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE,
		},
	}

	//requestStr := "{\"type\":15,\"info\":{\"session_id\":\"3687224344839904972\",\"message\":{\"message_id\":\"7551435481111744957\",\"timestamp_ms\":1758205583,\"type\":1,\"text\":\"哪些条件符合剧烈急性毒性的判定界限？\"},\"member_id\":401969},\"resp_message_id\":\"7551435481111794857\",\"header\":{\"ip\":\"36.112.72.229\",\"sdid\":\"1855254235354161152\",\"udid\":\"WAYUPvvgCBuPTmKD7ihWgHj8b7tUkDEW6D0=\",\"client_source\":1,\"traffic_source\":29,\"version\":\"v2\"},\"chat_style\":1,\"prev_message_id\":\"0\",\"curr_reference_mount\":[{\"mount_base\":{\"knowledge_base_type\":3,\"knowledge_base_id\":7551246014350308810,\"knowledge_base_name\":\"危险化学品辨识指南\",\"visibility\":2}}],\"chat_model\":1}"
	//json.Unmarshal([]byte(requestStr), request)

	// 初始化 productContext
	//productContext := discover_model.NewDiscoverTabContext(request)
	//requestContext := entities.NewRequestContextFromChatRequest(request, getConfigMap(proto.ChatType_ZHIDA_V2))
	//requestContext.SetProductContext(productContext)
	//requestContext.SetAbParamMap(getAbParamMap(proto.ChatType_ZHIDA_V2))
	//requestContext.SetAbGivenValue(macro.ZlabSceneIdWebStandardDomain, map[string]string{"ws_web_rel_opt": "4"})

	return request

}

func getConfigMap(chatType proto.ChatType) map[string]map[string]string {
	// 获取当前图配置
	graphLogicConfig, isExist := conf.GetGraphConfig(conf.BuildLogicConfigName(graph_constant.ApiStreamChat, chatType.String()))
	if !isExist {
		return map[string]map[string]string{}
	}
	return graphLogicConfig.GetBizConfigMap()
}

func getAbParamMap(chatType proto.ChatType) map[zlab.SceneId][]zlab.ZlabValue {
	// 获取当前图配置
	graphLogicConfig, isExist := conf.GetGraphConfig(conf.BuildLogicConfigName(graph_constant.ApiStreamChat, chatType.String()))
	if !isExist {
		return map[zlab.SceneId][]zlab.ZlabValue{}
	}
	return graphLogicConfig.GetAbParamMap()
}
