package dialog

import (
	"context"
	"flag"
	"fmt"
	"math/rand"
	"testing"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	dialogService "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/dialog_record"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"github.com/spf13/cast"
	"github.com/stretchr/testify/assert"
)

// go test -run TestDialogRecordSaveMain -v -args -g_message_id 11133332222 -q_message_id 11133332222228 -a_message_id 11133332222229

var (
	gMessageId int64
	qMessageId int64
	aMessageId int64
)

func init() {
	flag.Int64Var(&gMessageId, "g_message_id", 0, "组ID，同一组下 只有一对未过期的message")
	flag.Int64Var(&qMessageId, "q_message_id", 0, "Query 消息ID")
	flag.Int64Var(&aMessageId, "a_message_id", 0, "Answer 消息ID")

}

func TestDialogRecordSaveMain(t *testing.T) {
	flag.Parse()
	ctx := context.Background()
	if gMessageId == 0 {
		gMessageId = qMessageId
	}

	sessionId := int64(13333333336)
	queryMessage := createQuery(&message.TextMessage{
		Content: "你好啊 Hello Hi 我是Query",
	}, sessionId, gMessageId, qMessageId)
	answerMessage := createAnswer(&message.TextMessage{
		Content: "你好啊 Hello Hi 我是Answer",
	}, sessionId, cast.ToInt64(queryMessage.MessageId), aMessageId)

	textDialogId, textErr := dialogService.DefaultDialogService.SaveOrUpdateDialogWrapper(ctx, &message.DialogueWrapper{
		Query:  queryMessage,
		Answer: answerMessage,
	})
	if textErr != nil {
		fmt.Printf("ERROR 插入文本对话数据失败 => %v \n", textErr)
		return
	} else {
		fmt.Printf("SUCCESS 插入文本对话数据成功 数据Id => %v \n", textDialogId)
	}

	rows, err := dialogService.DefaultDialogService.GetDialogListBySessionId(ctx, sessionId, 50)
	if err != nil {
		fmt.Printf("ERROR 查询对话历史失败 => %v \n", err)
		return
	} else {
		fmt.Println("SUCCESS 查询对话历史成功")
		for _, row := range rows {
			fmt.Printf("数据 => %s \n", util.GetJSONIgnoreError(*row))
		}
	}
	assert.Equal(t, 2, len(rows))
}

func createQuery(msg *message.TextMessage, sessionId int64, messageGroupId int64, messageId int64) *model.DialogRecord {
	if messageId == 0 {
		messageId = rand.Int63()
	}
	jsonString, _ := msg.ToJsonString()
	return &model.DialogRecord{
		MemberId:        rand.Int63(),
		AiId:            rand.Int63(),
		MessageGroupId:  cast.ToString(messageGroupId),
		MessageId:       cast.ToString(messageId),
		ConversationId:  cast.ToString(rand.Int63()),
		Scene:           proto.ChatType_DISCOVER_TAB.String(),
		MessageType:     int64(proto.ChatMessageType_TEXT),
		MessageContent:  msg.Content,
		ParentMessageId: "",
		RecordAt:        time.Now(),
		Message:         jsonString,
		ErrorType:       model.DialogErrorTypeNormal.ToConvert(),
		RoleType:        model.RoleTypeUser.ToConvert(),
		CreateType:      model.DialogCreateTypeLLM.ToConvert(),
		SessionId:       sessionId,
	}
}

func createAnswer(msg *message.TextMessage, sessionId int64, parentMessageId int64, messageId int64) *model.DialogRecord {
	if messageId == 0 {
		messageId = rand.Int63()
	}
	jsonString, _ := msg.ToJsonString()
	return &model.DialogRecord{
		MemberId:        rand.Int63(),
		AiId:            rand.Int63(),
		MessageId:       cast.ToString(messageId),
		ConversationId:  cast.ToString(rand.Int63()),
		Scene:           proto.ChatType_DISCOVER_TAB.String(),
		MessageType:     int64(proto.ChatMessageType_TEXT),
		MessageContent:  msg.Content,
		ParentMessageId: cast.ToString(parentMessageId),
		RecordAt:        time.Now(),
		Message:         jsonString,
		ErrorType:       model.DialogErrorTypeNormal.ToConvert(),
		RoleType:        model.RoleTypeAI.ToConvert(),
		CreateType:      model.DialogCreateTypeLLM.ToConvert(),
		SessionId:       sessionId,
	}

	/**
	ID              int64     `json:"id" borm:"primary_key"`
	RoleType        string    `json:"role_type"`                  // 角色类型 USER AI
	Scene           string    `json:"scene"`                      // 场景 AI_TAB SEARCH_TAB
	MemberId        int64     `json:"member_id"`                  // 用户Id
	AiId            int64     `json:"ai_id"`                      // AI Id
	SessionId       int64     `json:"session_id"`                 // 会话Id
	ConversationId  string    `json:"conversation_id"`            // 场景 AI_TAB SEARCH_TAB
	MessageGroupId  string    `json:"message_group_id"`           // 消息组Id（主要用于修改标题和重答）
	MessageId       string    `json:"message_id"`                 // 消息Id
	ParentMessageId string    `json:"parent_message_id"`          // 父级消息Id
	Message         string    `json:"message" borm:""`            // 消息
	MessageContent  string    `json:"message_content" borm:""`    // 消息文本 当消息类型为文本时有效
	MessageType     int64     `json:"message_type"`               // 消息类型 0:未知 1:文本
	RecordAt        time.Time `json:"record_at"`                  // 消息创建时间
	CreateType      int64     `json:"create_type"`                // 创建类型 0未知 1:用户输入 2:静态库输出 3:LLM输出
	ErrorType       int64     `json:"error_type"`                 // 异常类型 0:正常 安全拒答 安全兜底 LLM兜底
	Exceeded        int64     `json:"exceeded"`                   // 是否过期 0否 1是
	Deleted         int64     `json:"deleted"`                    // 是否删除 0否 1是
	CreatedAt       time.Time `json:"created_at" borm:"readonly"` // 创建时间 设置borm只读，利用数据库的能力生成 CreatedAt
	UpdatedAt       time.Time `json:"updated_at" borm:"readonly"` // 修改时间 设置borm只读，利用数据库的能力生成 CreatedAt
	*/
}
