package main

import (
	"context"
	"fmt"
	"math/rand"
	"time"

	"git.apache.org/thrift.git/lib/go/thrift"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-eval-regulate-core/eval_regulate_core_thrift/risk_check"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"github.com/spf13/cast"
)

func main() {

	ctx := context.Background()

	sessionId := rand.Int63()

	var dialogRecords []*message.DialogueWrapper

	clientSource := "PC"
	trafficSource := "zhida"

	// step 1
	step1 := message.DialogueWrapper{}
	dialogRecords = append(dialogRecords, &step1)
	step1.Query = createDto(&message.TextMessage{
		Content: "你好啊 Hello Hi",
	}, sessionId, model.RoleTypeUser)
	// RiskCheck 调用安全审核
	result, err := impl.DefaultRiskCheckRPCImpl.RiskCheckDialog(ctx, &rpc.RiskCheckParams{
		Contents:      message.NewDialogueWrapperArr(&dialogRecords).ToConvertRiskCheckContents(),
		MemberId:      133333333333333333,
		IP:            "36.112.72.230",
		DeviceId:      "12321312",
		SourceId:      rpc.RiskCheckSourceAiQuery,
		ClientSource:  clientSource,
		TrafficSource: trafficSource,
		QueryExtra: &risk_check.QuestionInfo{
			QuestionType: thrift.StringPtr(rpc.RiskCheckQuestionTypeUser.ToConvert()),
		},
	})
	printRiskRes("step1 Query", result, err)

	step1.Answer = createDto(&message.TextMessage{
		Content: "我是智能机器人 小知 有什么 可以帮您",
	}, sessionId, model.RoleTypeUser)

	// RiskCheck 调用安全审核
	result, err = impl.DefaultRiskCheckRPCImpl.RiskCheckDialog(ctx, &rpc.RiskCheckParams{
		Contents:      message.NewDialogueWrapperArr(&dialogRecords).ToConvertRiskCheckContents(),
		MemberId:      133333333333333333,
		IP:            "36.112.72.230",
		DeviceId:      "12321312",
		SourceId:      rpc.RiskCheckSourceAiAnswer,
		AnswerExtra:   rpc.NewRiskAnswerInfo(),
		ClientSource:  clientSource,
		TrafficSource: trafficSource,
	})
	printRiskRes("step1 Answer", result, err)
	fmt.Println("\n===========================================")

	// step 1
	step2 := message.DialogueWrapper{}
	dialogRecords = append(dialogRecords, &step2)
	step2.Query = createDto(&message.TextMessage{
		Content: "土豆土豆我是地瓜",
	}, sessionId, model.RoleTypeUser)
	// RiskCheck 调用安全审核
	result, err = impl.DefaultRiskCheckRPCImpl.RiskCheckDialog(ctx, &rpc.RiskCheckParams{
		Contents:      message.NewDialogueWrapperArr(&dialogRecords).ToConvertRiskCheckContents(),
		MemberId:      133333333333333333,
		IP:            "36.112.72.230",
		DeviceId:      "12321312",
		SourceId:      rpc.RiskCheckSourceAiQuery,
		ClientSource:  clientSource,
		TrafficSource: trafficSource,
		QueryExtra: &risk_check.QuestionInfo{
			QuestionType: thrift.StringPtr(rpc.RiskCheckQuestionTypeAlgo.ToConvert()),
		},
	})
	printRiskRes("step2 Query", result, err)

	step2.Answer = createDto(&message.TextMessage{
		Content: "你不是地瓜",
	}, sessionId, model.RoleTypeUser)

	// RiskCheck 调用安全审核
	result, err = impl.DefaultRiskCheckRPCImpl.RiskCheckDialog(ctx, &rpc.RiskCheckParams{
		Contents:      message.NewDialogueWrapperArr(&dialogRecords).ToConvertRiskCheckContents(),
		MemberId:      133333333333333333,
		IP:            "36.112.72.230",
		DeviceId:      "12321312",
		SourceId:      rpc.RiskCheckSourceAiAnswer,
		ClientSource:  clientSource,
		TrafficSource: trafficSource,
		AnswerExtra:   rpc.NewRiskAnswerInfo(),
	})
	printRiskRes("step2 Answer", result, err)

	fmt.Println("\n===================== 测试 兴趣词 ======================")
	fmt.Println()
	result, err = impl.DefaultRiskCheckRPCImpl.RiskCheckInterestWord(ctx, "地瓜", "TEST")
	printRiskRes("InterestWord step1: ", result, err)

	fmt.Println()
	result, err = impl.DefaultRiskCheckRPCImpl.RiskCheckInterestWord(ctx, "土豆土豆我是地瓜", "TEST")
	printRiskRes("InterestWord step2: ", result, err)

}

func printRiskRes(step string, res *rpc.RiskCheckResp, err error) {
	fmt.Println(step, "  输出安全审核结果 => ", util.GetJSONIgnoreError(*res), "  error => ", err)
}

func createDto(msg *message.TextMessage, sessionId int64, roleType model.RoleType) *model.DialogRecord {
	return &model.DialogRecord{
		MemberId:        rand.Int63(),
		AiId:            rand.Int63(),
		MessageId:       cast.ToString(rand.Int63()),
		ConversationId:  cast.ToString(rand.Int63()),
		Scene:           proto.ChatType_DISCOVER_TAB.String(),
		MessageType:     int64(proto.ChatMessageType_TEXT),
		MessageContent:  msg.Content,
		ParentMessageId: "",
		RecordAt:        time.Now(),
		ErrorType:       model.DialogErrorTypeNormal.ToConvert(),
		RoleType:        roleType.ToConvert(),
		CreateType:      model.DialogCreateTypeLLM.ToConvert(),
		SessionId:       sessionId,
	}
}
