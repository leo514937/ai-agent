package main

import (
	"context"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/portal/grpc"
	"github.com/samber/lo"
)

// go run pkg/tools/biz/recall_service/main.go
func main() {
	ctx := context.Background()
	resources.Init(graph_constant.ApiRecall)
	recallService := grpc.NewAispRecallService()
	req := &proto.ZhidaRecallRequest{
		MemberId: 117223006,
		Query:    "如何评价明末渊虚之羽",
		RecallExtInfo: &proto.RecallExtInfo{
			ChatType:        proto.ChatType_ZHIDA_V2,
			ClientSource:    proto.ClientSource_PC_WEB,
			TrafficSource:   proto.TrafficSource_zhida,
			MessageId:       "7525296960801341774",
			RequestId:       "33d7d20eae81e2cf1fa7c0a0f3944c17",
			ParentRequestId: "da0c5f4a51d7b85e25fe03f9a4d9e7be",
			Intention:       string(macro.GetQueryRouteSearch()),
			ReferenceMount: []*proto.ReferenceMount{
				{
					MountBase: &proto.PersonalKnowledgeBase{
						Visibility: proto.KnowledgeBaseVisibility_PUBLIC_FEATURE,
					},
				},
				{
					MountBase: &proto.PersonalKnowledgeBase{
						KnowledgeBaseId:   7474549483516594575,
						KnowledgeBaseType: proto.PersonalKnowledgeBaseType_PKB_RSS,
					},
				},
			},
			KnowledgeBases: []proto.KnowledgeBaseType{
				proto.KnowledgeBaseType_KBT_GLOBAL,
				proto.KnowledgeBaseType_KBT_ZHIHU,
				proto.KnowledgeBaseType_KBT_PAPER,
				proto.KnowledgeBaseType_KBT_PERSONAL_KNOWLEDGE_BASE,
			},
		},
	}
	// 请求与返回
	fmt.Println(fmt.Sprintf("req:%s", util.GetJSONIgnoreError(req)))
	resp, err := recallService.GetZhidaRecall(ctx, req)
	if err != nil {
		panic(err)
	}
	fmt.Println(fmt.Sprintf("============> resp:%s", util.GetJSONIgnoreError(resp)))

	// 返回结果计数
	recallSourceCount := lo.CountValues(lo.Map(resp.GetRecallItems(), func(item *proto.ZhidaRecallItem, _ int) string {
		return item.GetRecallSource()
	}))
	fmt.Println(fmt.Sprintf("============> recallSourceCount:%s", util.GetJSONIgnoreError(recallSourceCount)))

}
