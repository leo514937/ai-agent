package request

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
)

func NewStreamChatRequest(
	host string,
	text string,
	chatType proto.ChatType,
	sessionID string,
	memberID int64,
	chatStyle proto.ChatStyle,
	clientSource proto.ClientSource,
	trafficSource proto.TrafficSource,
	sourceContent *proto.DocAboutQueriesRequest,
) *StreamChatRequest {
	qMsg := &StreamChatRequest{
		text:            text,
		chatType:        chatType,
		chatMessageType: proto.ChatMessageType_TEXT,
		sessionID:       sessionID,
		memberID:        memberID,
		chatStyle:       chatStyle,
		clientSource:    clientSource,
		trafficSource:   trafficSource,
		sourceContent:   sourceContent,
	}

	client, ctx := getClient(host)
	qMsg.host = host
	qMsg.ctx = ctx
	qMsg.client = client
	return qMsg
}

func NewCreateSessionRequest(
	host string,
	chatType proto.ChatType,
	memberID int64,
	extraInfo *proto.ExtraInfo,
	dialogs []*proto.DialogMessageWrapper,
) *CreateSessionRequest {
	qMsg := &CreateSessionRequest{
		chatType:  chatType,
		memberId:  memberID,
		extraInfo: extraInfo,
		message:   dialogs,
	}

	client, ctx := getClient(host)
	qMsg.host = host
	qMsg.ctx = ctx
	qMsg.client = client
	return qMsg
}

func NewDigitalAuthorChatRequest(
	host string,
	text string,
) *DigitalAuthorChatRequest {
	qMsg := &DigitalAuthorChatRequest{
		text:            text,
		chatMessageType: proto.ChatMessageType_TEXT,
	}

	client, ctx := getClient(host)
	qMsg.host = host
	qMsg.ctx = ctx
	qMsg.client = client
	return qMsg
}

func NewQueryMergeRequest(
	host string,
	text string,
	buildType proto.BuildQueryType,
	sessionID string,
	memberID int64,
) *QueryMergeRequest {
	qMsg := &QueryMergeRequest{
		text:            text,
		buildType:       buildType,
		chatMessageType: proto.ChatMessageType_TEXT,
		sessionID:       sessionID,
		memberID:        memberID,
	}

	client, ctx := getClient(host)
	qMsg.host = host
	qMsg.ctx = ctx
	qMsg.client = client
	return qMsg
}

func NewSuggestQueriesRequest(
	host string,
	text string,
	suggestQueriesType proto.SuggestQueriesType,
	sessionID string,
	messageId string,
	memberID int64,
	extraInfo *proto.ExtraInfo,
	clientSource proto.ClientSource,
	trafficSource proto.TrafficSource,
	docAboutQueriesRequest *proto.DocAboutQueriesRequest,
	specifiedDocAboutQueriesRequest []*proto.DocAboutQueriesRequest,
) *SuggestQueriesRequest {

	qMsg := &SuggestQueriesRequest{
		text:                            text,
		suggestQueriesType:              suggestQueriesType,
		chatMessageType:                 proto.ChatMessageType_TEXT,
		sessionID:                       sessionID,
		memberID:                        memberID,
		messageId:                       messageId,
		extraInfo:                       extraInfo,
		docAboutQueriesRequest:          docAboutQueriesRequest,
		specifiedDocAboutQueriesRequest: specifiedDocAboutQueriesRequest,
		clientSource:                    clientSource,
		trafficSource:                   trafficSource,
	}

	client, ctx := getClient(host)
	qMsg.host = host
	qMsg.ctx = ctx
	qMsg.client = client
	return qMsg
}

// getClient 获取 client
func getClient(host string) (proto.AispChatServiceClient, context.Context) {
	ctx := context.Background()
	conn, err := grpc.DialContext(ctx, host)
	if err != nil {
		panic(err)
	}

	serviceClient := proto.NewAispChatServiceClient(conn)
	return serviceClient, ctx
}
