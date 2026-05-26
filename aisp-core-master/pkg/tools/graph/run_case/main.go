package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/graph/conf/digital_author_conf"
	digital_model "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/google/uuid"
	"github.com/tealeg/xlsx"
)

var respDescMap = map[proto.ChatRespType]string{
	proto.ChatRespType_UNKNOWN_RESP: "未知返回",
	proto.ChatRespType_GREETING:     "创作者问候语",
	proto.ChatRespType_DOMAIN:       "领域返回",
	proto.ChatRespType_NON_DOMAIN:   "非领域相关回答",
	proto.ChatRespType_SMALL_TALK:   "闲聊类回答",
	proto.ChatRespType_REFUSE:       "安全拒答",
	proto.ChatRespType_RED_LINE:     "红线必答",
	proto.ChatRespType_TASK:         "出任务",
	proto.ChatRespType_UNANSWERABLE: "无法回答",
}

/**
脚本用于执行 case，产出两个文件:
1、process_log.txt 过程日志，实时输出
2、output.xlsx 最终结果，执行完输出
nohup go run pkg/tools/graph/run_case/main.go --multi=true 2>&1 >log.log &
*/

var nowConversationId = ""
var hist []*proto.HistChatMessage

func main() {
	isMulti := flag.Bool("multi", true, "是否跑多轮")
	flag.Parse()

	//打开 Excel 文件
	file, err := xlsx.OpenFile("input.xlsx")
	if err != nil {
		fmt.Println(err)
		return
	}
	// 获取第一个工作表
	sheet := file.Sheets[0]

	resources.Init(graph_constant.ApiDigitalAuthorChat)
	var outPutLog, _ = os.Create("process_log.txt")
	defer outPutLog.Close()
	if err != nil {
		fmt.Println(err)
		return
	}

	if err != nil {
		fmt.Println(err)
		return
	}

	txn, ctx := log.StartTransaction("tools_graph")
	defer txn.End(ctx)

	// 遍历所有行
	for i, row := range sheet.Rows {
		// 获取 A 列单元格
		authorIdrow := row.Cells[0]
		userInput := row.Cells[1]
		conversation := row.Cells[2]
		theme := row.Cells[3]
		if i == 0 {
			// 第一行是列名，创建名为 output 的列
			row.AddCell().SetValue("answer")
			row.AddCell().SetValue("recall")
			row.AddCell().SetValue("finalRecall")
			row.AddCell().SetValue("chatInput")
			row.AddCell().SetValue("security")
			continue
		}

		// 将 A 列单元格内容处理后输出到 B 列
		authorId := authorIdrow.String()
		question := userInput.String()
		themes := theme.String()
		conversationId := conversation.String()

		if !*isMulti {
			conversationId = uuid.NewString()
		}
		answer, recall, finalRecall, chatInput, security := getAnswer(ctx, conversationId, question, authorId, themes)

		fmt.Printf("question:%s,answer:%s,intention:%s", question, answer, finalRecall)
		outPutLog.WriteString(fmt.Sprintf("===============>row:%d\n", i+1))
		outPutLog.WriteString(fmt.Sprintf("question:%s\n", question))
		outPutLog.WriteString(fmt.Sprintf("answer:%s\n", answer))
		outPutLog.WriteString(fmt.Sprintf("chatInput:%s\n", chatInput))
		outPutLog.WriteString(fmt.Sprintf("security:%s\n", security))

		row.AddCell().SetValue(answer)
		row.AddCell().SetValue(recall)
		row.AddCell().SetValue(finalRecall)
		row.AddCell().SetValue(chatInput)
		row.AddCell().SetValue(security)
	}

	// 保存文件
	err = file.Save("output01.xlsx")
	if err != nil {
		fmt.Println(err)
		return
	}

}

func getAnswer(ctx context.Context, conversationId string, userInput string, authorId string, theme string) (answer string, recall string, finalRecall string, chatInput string, security string) {

	if conversationId != nowConversationId {
		nowConversationId = conversationId
		hist = []*proto.HistChatMessage{}
	} else {
		hist = append(hist, &proto.HistChatMessage{
			Message: &proto.ChatMessage{
				MessageId:   util.Int64String(int64(uuid.New().ID())),
				TimestampMs: util.TimeUnixMilli(),
				Type:        proto.ChatMessageType_TEXT,
				Text:        userInput,
			},
			SenderId: "117223006",
			Role:     proto.Role_USER,
			RespType: proto.ChatRespType_UNKNOWN_RESP,
		})
	}

	request := &proto.DigitalAuthorRequestInfo{
		ConversationId: "",
		Message: &proto.ChatMessage{
			MessageId:   util.Int64String(int64(uuid.New().ID())),
			TimestampMs: util.TimeUnixMilli(),
			Type:        proto.ChatMessageType_TEXT,
			Text:        userInput,
		},
		RespMessageId: util.Int64String(int64(uuid.New().ID())),
		SenderId:      "117223006",
		ReceiverId:    authorId,
		BizInfo: &proto.DigitalAuthorBizInfo{
			HistChat:           hist,
			BayesFirstcategory: []string{"法律"},
			TopicNames:         []string{theme},
			EnableOnsite:       true,
			EnableUniversal:    false,
			Tasks: []*proto.TaskInfo{
				{
					Id:          1,
					TaskName:    "留资",
					Description: "当用户咨询电信诈骗案件时，请用户留下联系方式",
					Goal:        proto.TaskGoal_TEL_NUMBER,
				},
				{
					Id:          2,
					TaskName:    "留资",
					Description: "当用户咨询存在不当行为，是否会影响政审时，请引导用户说明基本信息后留下联系方式",
					Goal:        proto.TaskGoal_TEL_NUMBER,
				},
			},
			AuthorName: "用户名称",
		},
		IsExemptSecurity: false,
	}

	productContext := digital_model.NewDigitalAuthorContext(request)
	requestContext := entities.NewRequestContextForDigitalChat(request, productContext, digital_author_conf.LogicBizConfigMap)
	itemList, _, _, err := graph.RunGraph(ctx, requestContext, nil)
	if err != nil && len(itemList) == 0 {
		err = errors.New("empty response")
	}
	result := itemList[0].Text
	respType := respDescMap[itemList[0].ChatRespType]

	answer = fmt.Sprintf("【%s】%s", respType, result)

	hist = append(hist, &proto.HistChatMessage{
		Message: &proto.ChatMessage{
			MessageId:   util.Int64String(int64(uuid.New().ID())),
			TimestampMs: util.TimeUnixMilli(),
			Type:        proto.ChatMessageType_TEXT,
			Text:        result,
		},
		SenderId: authorId,
		Role:     proto.Role_AI,
		RespType: proto.ChatRespType_DOMAIN,
	})

	hitTask := productContext.HitTask()
	if hitTask != nil && hitTask.GetId() != 0 {
		taskDesc := fmt.Sprintf("AuthorTask(%d,%s,%s)", hitTask.GetId(), hitTask.GetGoal().String(), hitTask.GetDescription())
		result = fmt.Sprintf("%s\n%s", result, taskDesc)
	}

	recall = util.GetJSONIgnoreError(requestContext.Tracing().ProcessTracing.GetRecallIndex())
	finalRecall = util.GetJSONIgnoreError(requestContext.Tracing().ProcessTracing.GetFinalIndex())

	for _, tracing := range requestContext.GetLogicTracingMap() {
		if tracing.GetLogicName() == "inDomainChat" || tracing.GetLogicName() == "smallTalkChat" {
			chatInput = util.GetJSONIgnoreError(tracing.GetLogicInput())
		}
	}

	return
}
