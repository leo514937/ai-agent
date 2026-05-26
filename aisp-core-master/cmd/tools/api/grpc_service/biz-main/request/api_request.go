package request

import (
	"context"
	"fmt"

	"git.in.zhihu.com/go/base/telemetry/log"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
)

type AbsQuest struct {
	host   string
	ctx    context.Context
	client proto.AispBizServiceClient
}

type RecallSearchRequest struct {
	memberId           int64
	recallSearchType   proto.KbRecallSearchType
	knowledgeBaseType  []proto.PersonalKnowledgeBaseType
	searchRecallDomain []proto.KbRecallSearchField
	AbsQuest
}

// DoRecallSearch 真正模拟客户端 发起 DoRecallSearch 请求
func (rMsg *RecallSearchRequest) DoRecallSearch(ctx context.Context, query string) {
	request := &proto.KbRecallSearchRequest{
		MemberId:          rMsg.memberId,
		Query:             query,
		RecallSearchType:  rMsg.recallSearchType,
		KnowledgeBaseType: rMsg.knowledgeBaseType,
		SearchRecallField: rMsg.searchRecallDomain,
	}
	log.Errorf(ctx, "print.recall_search.input => %s", util.GetJSONIgnoreError(request))
	resp, err := rMsg.client.KbRecallSearch(ctx, request)
	if err != nil {
		log.Errorf(ctx, "grpc failed.err:%v", err)
	}

	fmt.Printf("输出 DoRecallSearch Response => %v \n", util.GetJSONIgnoreError(resp))
}

type BuildKnowledgeBaseIndexRequest struct {
	memberId          int64
	docId             int64
	docType           proto.DocType
	knowledgeBaseId   int64
	knowledgeBaseName string
	knowledgeBaseType proto.PersonalKnowledgeBaseType
	actionType        proto.KbActionType
	AbsQuest
}

// DoBuildPersonalKnowledgeBaseIndex 真正模拟客户端 发起 DoBuildPersonalKnowledgeBaseIndex 请求
func (rMsg *BuildKnowledgeBaseIndexRequest) DoBuildPersonalKnowledgeBaseIndex(ctx context.Context) {
	request := &proto.BuildPersonalKnowledgeBaseIndexRequest{
		MemberId:          rMsg.memberId,
		DocId:             rMsg.docId,
		DocType:           rMsg.docType,
		KnowledgeBaseId:   rMsg.knowledgeBaseId,
		KnowledgeBaseName: rMsg.knowledgeBaseName,
		KnowledgeBaseType: rMsg.knowledgeBaseType,
		ActionType:        rMsg.actionType,
	}
	log.Infof(ctx, "print.build_kb_index.input => %s", util.GetJSONIgnoreError(request))
	resp, err := rMsg.client.BuildPersonalKnowledgeBaseIndex(ctx, request)
	if err != nil {
		log.Errorf(ctx, "grpc failed.err:%v", err)
	}

	fmt.Printf("输出 DoBuildPersonalKnowledgeBaseIndex Response => %v \n", util.GetJSONIgnoreError(resp))
}
