package request

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
)

func NewRecallSearchRequest(
	host string,
	memberID int64,
	recallSearchType proto.KbRecallSearchType,
	knowledgeBaseTypes []proto.PersonalKnowledgeBaseType,
	searchRecallDomains []proto.KbRecallSearchField,
) *RecallSearchRequest {
	qMsg := &RecallSearchRequest{
		memberId:           memberID,
		recallSearchType:   recallSearchType,
		knowledgeBaseType:  knowledgeBaseTypes,
		searchRecallDomain: searchRecallDomains,
	}

	client, ctx := getClient(host)
	qMsg.host = host
	qMsg.ctx = ctx
	qMsg.client = client
	return qMsg
}

func NewBuildKnowledgeBaseIndexRequest(
	host string,
	memberID int64,
	docId int64,
	docType proto.DocType,
	knowledgeBaseId int64,
	knowledgeBaseName string,
	knowledgeBaseType proto.PersonalKnowledgeBaseType,
	actionType proto.KbActionType,
) *BuildKnowledgeBaseIndexRequest {
	qMsg := &BuildKnowledgeBaseIndexRequest{
		memberId:          memberID,
		docId:             docId,
		docType:           docType,
		knowledgeBaseId:   knowledgeBaseId,
		knowledgeBaseName: knowledgeBaseName,
		knowledgeBaseType: knowledgeBaseType,
		actionType:        actionType,
	}

	client, ctx := getClient(host)
	qMsg.host = host
	qMsg.ctx = ctx
	qMsg.client = client
	return qMsg
}

// getClient 获取 client
func getClient(host string) (proto.AispBizServiceClient, context.Context) {
	ctx := context.Background()
	conn, err := grpc.DialContext(ctx, host)
	if err != nil {
		panic(err)
	}

	serviceClient := proto.NewAispBizServiceClient(conn)
	return serviceClient, ctx
}
