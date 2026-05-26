package request

import (
	"context"
	"fmt"
	"io"
	"math/rand"
	"time"

	"git.in.zhihu.com/go/base/telemetry/log"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"github.com/spf13/cast"
	"google.golang.org/protobuf/encoding/protojson"
)

type AbsQuest struct {
	host   string
	ctx    context.Context
	client proto.AispChatServiceClient
}

type StreamChatRequest struct {
	text            string
	chatType        proto.ChatType
	chatMessageType proto.ChatMessageType
	sessionID       string
	memberID        int64
	chatStyle       proto.ChatStyle
	clientSource    proto.ClientSource
	trafficSource   proto.TrafficSource
	sourceContent   *proto.DocAboutQueriesRequest
	AbsQuest
}

type DigitalAuthorChatRequest struct {
	text            string
	chatType        proto.ChatType
	chatMessageType proto.ChatMessageType
	AbsQuest
}

type CreateSessionRequest struct {
	chatType  proto.ChatType
	memberId  int64
	extraInfo *proto.ExtraInfo
	message   []*proto.DialogMessageWrapper
	AbsQuest
}

type QueryMergeRequest struct {
	text            string
	buildType       proto.BuildQueryType
	chatMessageType proto.ChatMessageType
	sessionID       string
	memberID        int64
	AbsQuest
}

type SuggestQueriesRequest struct {
	text                            string
	suggestQueriesType              proto.SuggestQueriesType
	chatMessageType                 proto.ChatMessageType
	docAboutQueriesRequest          *proto.DocAboutQueriesRequest
	specifiedDocAboutQueriesRequest []*proto.DocAboutQueriesRequest
	sessionID                       string
	memberID                        int64
	messageId                       string
	extraInfo                       *proto.ExtraInfo
	clientSource                    proto.ClientSource
	trafficSource                   proto.TrafficSource
	AbsQuest
}

// DoStreamChat 真正模拟客户端 发起 StreamChat 请求
func (rMsg *StreamChatRequest) DoStreamChat(ctx context.Context,
	messageGroupId int64, queryMessageId int64, answerMessageId int64,
	knowledgeBases []proto.KnowledgeBaseType,
	currMounts []*proto.ReferenceMount,
	hisMounts []*proto.ReferenceMount,
	modelArgs *proto.ModelArgs,
	chatModel proto.ChatModel,
	version string,
	recallContentIds []string,
	operationId int64,
) {

	messageGroupIdStr := cast.ToString(messageGroupId)
	queryMessageIdStr := cast.ToString(queryMessageId)
	answerMessageIdStr := cast.ToString(answerMessageId)
	if queryMessageId == 0 {
		queryMessageId = rand.Int63()
		if messageGroupId != 0 {
			queryMessageId = messageGroupId
		}
		queryMessageIdStr = cast.ToString(queryMessageId)
	}
	if answerMessageId == 0 {
		answerMessageId = rand.Int63()
		answerMessageIdStr = cast.ToString(answerMessageId)
	}
	if messageGroupId == 0 {
		messageGroupId = queryMessageId
		messageGroupIdStr = cast.ToString(messageGroupId)
	}

	request := &proto.ChatRequest{
		Type:                  rMsg.chatType,
		Info:                  buildRequestInfoByAll(rMsg.text, rMsg.chatMessageType, rMsg.sessionID, rMsg.memberID, queryMessageIdStr),
		RecallContentIds:      recallContentIds,
		RespMessageId:         answerMessageIdStr,
		KnowledgeBases:        knowledgeBases,
		CurrReferenceMount:    currMounts,
		HistoryReferenceMount: hisMounts,
		ChatStyle:             rMsg.chatStyle,
		PrevMessageId:         messageGroupIdStr,
		Header: &proto.RequestHeader{
			ClientSource:  rMsg.clientSource,
			TrafficSource: rMsg.trafficSource,
			Version:       version,
		},
		ChatExtraInfo: &proto.ChatExtraInfo{
			SourceContent: rMsg.sourceContent,
			MatchOrder:    1,
			ModelArgs:     modelArgs,
			OperationId:   operationId,
		},
		ChatModel: chatModel,
	}
	log.Infof(ctx, "print.chat.input => %s", util.GetJSONIgnoreError(request))
	resp, err := rMsg.client.StreamChat(ctx, request)
	if err != nil {
		log.Errorf(ctx, "grpc failed.err:%v", err)
	}
	receiveStream(ctx, resp)
}

// DoDigitalAuthorChat 真正模拟客户端 发起 DigitalAuthorChat 请求
func (rMsg *DigitalAuthorChatRequest) DoDigitalAuthorChat() {
	ctx := context.Background()
	request := &proto.DigitalAuthorRequestInfo{
		Message: buildMessage(rMsg.text, rMsg.chatMessageType),
	}

	resp, err := rMsg.client.DigitalAuthorChat(ctx, request)
	if err != nil {
		log.Errorf(ctx, "grpc failed.err:%v", err)
	}
	receiveStream(ctx, resp)
}

// DoQueryMergeRequest 真正模拟客户端 发起 QueryMerge 请求
func (rMsg *QueryMergeRequest) DoQueryMergeRequest() {
	// 组装消息
	req := &proto.BuildQueryRequest{
		Type: rMsg.buildType,
		Info: buildRequestInfo(rMsg.text, rMsg.chatMessageType, rMsg.sessionID, rMsg.memberID),
	}
	fmt.Println(req)
	resp, err := rMsg.client.BuildQuery(context.Background(), req)
	if err != nil {
		log.Errorf(rMsg.ctx, "grpc failed.err:%v", err)
	}
	fmt.Println("输出 QueryMergeResponse信息 => ", resp)
}

// DoSuggestQueriesRequest 真正模拟客户端 发起 词推荐 请求
func (rMsg *SuggestQueriesRequest) DoSuggestQueriesRequest() {
	// 组装消息
	req := &proto.SuggestQueriesRequest{
		Type:      rMsg.suggestQueriesType,
		Info:      buildRequestInfoByAll(rMsg.text, rMsg.chatMessageType, rMsg.sessionID, rMsg.memberID, rMsg.messageId),
		ExtraInfo: rMsg.extraInfo,
		Header: &proto.RequestHeader{
			ClientSource:  rMsg.clientSource,
			TrafficSource: rMsg.trafficSource,
		},
		DocAboutQueriesRequest:          rMsg.docAboutQueriesRequest,
		SpecifiedDocAboutQueriesRequest: rMsg.specifiedDocAboutQueriesRequest,
	}
	fmt.Println(req)
	start := time.Now() // 获取开始时间
	resp, err := rMsg.client.SuggestQueries(context.Background(), req)
	duration := time.Now().Sub(start).Milliseconds() // 计算耗时
	if err != nil {
		log.Errorf(rMsg.ctx, "grpc failed.err:%v", err)
	}
	fmt.Printf("耗时: %d 输出 SuggestQueriesResponse信息 => %s\n", duration, util.GetJSONIgnoreError(resp))
}

// DoCreateSessionRequest 创建Session
func (rMsg *CreateSessionRequest) DoCreateSessionRequest(ctx context.Context) string {
	// 组装消息
	req := &proto.CreateSessionRequest{
		Type:           rMsg.chatType,
		MemberId:       rMsg.memberId,
		ExtraInfo:      rMsg.extraInfo,
		DialogMessages: rMsg.message,
	}
	fmt.Println(req)
	start := time.Now() // 获取开始时间
	resp, err := rMsg.client.CreateSession(ctx, req)
	duration := time.Now().Sub(start).Milliseconds() // 计算耗时
	if err != nil {
		log.Errorf(rMsg.ctx, "grpc failed.err:%v", err)
	}
	fmt.Printf("耗时: %d 输出 CreateSessionRequest => %s\n", duration, util.GetJSONIgnoreError(resp))
	return cast.ToString(resp.GetSessionId())
}

// buildRequestInfo
func buildRequestInfo(
	text string,
	chatMessageType proto.ChatMessageType,
	sessionId string,
	memberId int64,
) *proto.RequestInfo {
	return buildRequestInfoByAll(text, chatMessageType, sessionId, memberId, cast.ToString(rand.Int63()))
}

// buildRequestInfo
func buildRequestInfoByAll(
	text string,
	chatMessageType proto.ChatMessageType,
	sessionId string,
	memberId int64,
	messageId string,
) *proto.RequestInfo {
	return &proto.RequestInfo{
		SessionId: sessionId,
		MemberId:  memberId,
		Message:   buildMessageById(text, messageId, chatMessageType),
	}
}

func buildMessage(text string,
	chatMessageType proto.ChatMessageType) *proto.ChatMessage {
	return buildMessageById(text, cast.ToString(rand.Int63()), chatMessageType)
}

func buildMessageById(text string, messageId string,
	chatMessageType proto.ChatMessageType) *proto.ChatMessage {
	return &proto.ChatMessage{
		MessageId:   messageId,
		TimestampMs: time.Now().UnixMilli(),
		Text:        text,
		Type:        chatMessageType,
	}
}

// receiveStream 打印转换输出Stream
func receiveStream(ctx context.Context, stream proto.AispChatService_StreamChatClient) {
	var currTime = time.Now()
	var lastMsg *proto.ChatResponse
	var stage proto.ChatStage
	for {
		msg, err := stream.Recv()
		// stream 结束条件
		if err == io.EOF {
			break
		}
		if err != nil {
			log.Errorf(ctx, "receiving stream error: %v", err)
			break
		}

		lastMsg = msg

		stageStr := fmt.Sprintf("CurrStage: %v  CurrStageState:%v", msg.GetChatStage().String(), msg.GetChatStageState().String())
		if msg.GetChatStage() != stage {
			stageStr += fmt.Sprintf(" --------- PastStage:%v", stage.String())
			stage = msg.GetChatStage()
		}
		stageStr += fmt.Sprintf("  ElapsedTime(ms): %d", time.Since(currTime).Milliseconds())
		fmt.Println(stageStr)

		if msg.GetChatStage() == proto.ChatStage_STAGE_RETRIEVAL {
			printRetrievalResponse(msg.GetRetrievalResponse())
		}

		if len(msg.GetRetrievalKeywords()) > 0 {
			fmt.Printf("Keywords: %v \n", msg.GetRetrievalKeywords())
		}

		if len(msg.GetCards()) > 0 {
			refsStr := fmt.Sprintf("Refs(Top3): All(%d): \n", len(msg.GetCards()))
			cards := msg.GetCards()
			for i, card := range cards {
				if i >= 3 {
					break
				}
				switch x := card.GetCardContent().(type) {
				case *proto.ChatCard_ZhihuRelevantSource:
					refsStr += fmt.Sprintf("    Ref(Zhihu) => %v \n", util.GetJSONIgnoreError(x.ZhihuRelevantSource))
				case *proto.ChatCard_OtherRelevantSource:
					refsStr += fmt.Sprintf("    Ref(Other) => %v \n", util.GetJSONIgnoreError(x.OtherRelevantSource))
				case *proto.ChatCard_ZhidaRelevantSource:
					refsStr += fmt.Sprintf("    Ref(Zhida) => %v \n", util.GetJSONIgnoreError(x.ZhidaRelevantSource))
				default:
				}
			}
			fmt.Println(refsStr)
		}

		if msg.GetThink() != "" {
			fmt.Printf("Think: \n%v\n\n", msg.GetThink())
		}
		if msg.GetMessage().GetText() != "" {
			fmt.Printf("Answer: \n%v\n", msg.GetMessage().GetText())
		}

		// 打印接收到的消息
		fmt.Println()
		fmt.Println()
		fmt.Println()
		time.Sleep(100 * time.Microsecond)
	}

	fmt.Println("FinalFormat => ")
	fmt.Printf("\n%v\n", formatJson(lastMsg))

}

func printRetrievalResponse(res []*proto.RetrievalResponse) {
	for _, msg := range res {
		//// 打印接收到的消息
		fmt.Printf("    RetrievalCurrStage: %v  RetrievalCurrStageState:%v  RetrievalFinalStageState:%v \n", msg.GetChatStage().String(), msg.GetChatStageState().String(), msg.GetRetrievalState().String())
		if msg.GetRetrievalTopic() != "" {
			fmt.Printf("    Retrieval-Topic: %v \n", msg.GetRetrievalTopic())
		}

		if len(msg.GetRetrievalKeywords()) > 0 {
			fmt.Printf("    Retrieval-Keywords: %v \n", msg.GetRetrievalKeywords())
		}

		if len(msg.GetRefs()) > 0 {
			refsStr := fmt.Sprintf("    Retrieval-Refs(Top3) All(%d): \n", len(msg.GetRefs()))
			for i, ref := range msg.GetRefs() {
				if i >= 3 {
					break
				}
				refsStr += fmt.Sprintf("        Ref(Zhida) => %v \n", util.GetJSONIgnoreError(ref))
			}
			fmt.Println(refsStr)
		}

		if msg.GetSummary() != "" {
			fmt.Printf("    Retrieval-Summary: %v\n", msg.GetSummary())
		}
		fmt.Println()
	}
}

func formatJson(obj *proto.ChatResponse) string {
	marshaler := protojson.MarshalOptions{
		EmitUnpopulated: true, // 保留零值
		UseProtoNames:   true, // 使用 proto 字段名
		Indent:          "  ", // 缩进（2个空格）
	}
	// 格式化输出JSON（带缩进）
	jsonData, _ := marshaler.Marshal(obj)
	return string(jsonData)
}
