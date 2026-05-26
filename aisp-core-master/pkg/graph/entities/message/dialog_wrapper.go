package message

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-eval-regulate-core/eval_regulate_core_thrift/risk_check"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"github.com/samber/lo"
)

type DialogueWrapper struct {
	// Query 问
	Query *model.DialogRecord
	// Answer 答
	Answer *model.DialogRecord
}

// ======== 历史消息转化器 ========

func NewDialogueWrapperArr(wrappers *[]*DialogueWrapper) *DialogueWrapperArr {
	return &DialogueWrapperArr{
		wrappers: wrappers,
	}
}

type DialogueWrapperArr struct {
	wrappers *[]*DialogueWrapper
}

func (w *DialogueWrapperArr) ToConvertRiskCheckContents() []*risk_check.CheckContentDetail {
	if w.wrappers == nil || len(*w.wrappers) == 0 {
		return []*risk_check.CheckContentDetail{}
	}

	// 处理 contents
	var contents []*risk_check.CheckContentDetail
	// 处理消息
	flatMap := lo.FlatMap(*w.wrappers, func(dialogueWrapper *DialogueWrapper, index int) []*model.DialogRecord {
		return []*model.DialogRecord{
			dialogueWrapper.Query,
			dialogueWrapper.Answer,
		}
	})
	for _, v := range flatMap {
		if v != nil {
			switch v.MessageType {
			// 处理 Content
			case int64(proto.ChatMessageType_TEXT):
				if v.MessageContent != "" {
					content := w.createRiskContent(v)
					contents = append(contents, content)
				}
			// TODO 处理 图片
			default:
			}
		}
	}
	return contents
}

// createRiskContent 创建Content
func (w *DialogueWrapperArr) createRiskContent(dialog *model.DialogRecord) *risk_check.CheckContentDetail {
	role := rpc.RoleTypeMap[dialog.RoleType]
	if role == "" {
		role = rpc.RoleTypeMap[model.RoleTypeUser.ToConvert()]
	}
	return &risk_check.CheckContentDetail{
		Role:     role,
		TextID:   dialog.MessageId,
		TextDesc: dialog.MessageContent,
	}
}

func HistToChatRequestMessage(histDialogue []*DialogueWrapper) []*dto.ChatRequestMessage {
	messages := make([]*dto.ChatRequestMessage, 0)
	for _, hist := range histDialogue {
		messages = append(messages, &dto.ChatRequestMessage{Content: hist.Query.MessageContent, Role: dto.ChatRequestMessageRoleUser})
		messages = append(messages, &dto.ChatRequestMessage{Content: hist.Answer.MessageContent, Role: dto.ChatRequestMessageRoleAI})
	}
	return messages
}
