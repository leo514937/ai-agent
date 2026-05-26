package prepare

import (
	"context"
	"fmt"
	"sort"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	digitalModel "git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/message"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/preparer"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/spf13/cast"
)

type DigitalAuthorChatHistoryLogic struct {
	*preparer.PreparerLogic[entities.RequestContext, entities.User, entities.Item, []*message.DialogueWrapper]
	maxCount int
}

func NewDigitalAuthorChatHistoryLogic(name string, config map[string]string) *DigitalAuthorChatHistoryLogic {
	res := &DigitalAuthorChatHistoryLogic{
		PreparerLogic: preparer.NewPreparerLogic[entities.RequestContext, entities.User, entities.Item, []*message.DialogueWrapper](name, config),
	}
	res.maxCount = 20 // 对话历史保留最近20轮
	res.FillUserFunc = res.realFillUser
	res.MergeUserFunc = res.realMergeUser
	return res
}

// todo: @wangran 改为从库中读取+接口传递降级
func (c *DigitalAuthorChatHistoryLogic) realFillUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) ([]*message.DialogueWrapper, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prepare.DigitalAuthorChatHistoryLogic.realFillUser")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	hitChats := requestCtx.GetBizContext().ProductContext().(*digitalModel.DigitalAuthorContext).HistChat()

	var result []*message.DialogueWrapper

	// 按照时间戳排序
	sort.Slice(hitChats, func(i, j int) bool {
		return hitChats[i].GetMessage().GetTimestampMs() < hitChats[j].GetMessage().GetTimestampMs()
	})

	isQuestion := false
	var currentDialog *message.DialogueWrapper

	for _, hitChat := range hitChats {
		currentSenderId := requestCtx.GetBizContext().MemberId()
		histSenderId := cast.ToInt64(hitChat.GetSenderId())

		// 过滤掉出任务卡的对话历史
		if hitChat.GetRespType() == proto.ChatRespType_TASK {
			continue
		}

		// 判断对方还是我方，下面if条件成立即为对方，否则我方。对方为 question，我方为 answer
		if currentSenderId == histSenderId {
			// 首次获得question，创建对话结构体
			if !isQuestion {
				if currentDialog != nil {
					result = append(result, currentDialog)
				}
				currentDialog = &message.DialogueWrapper{
					Query: genDialogRecord(requestCtx.GetBizContext().Scenes(), model.RoleTypeUser, currentSenderId, hitChat.GetMessage()),
				}
				isQuestion = true
			} else {
				// 再次获得question，合并结果
				currentDialog.Query.MessageContent = fmt.Sprintf("%s\n%s", currentDialog.Query.MessageContent, hitChat.GetMessage().GetText())
			}
		} else {
			// 首次获得 answer
			if isQuestion {
				currentDialog.Answer = genDialogRecord(requestCtx.GetBizContext().Scenes(), model.RoleTypeAI, currentSenderId, hitChat.GetMessage())
				isQuestion = false
			} else {
				// 如果以answer开头，丢弃掉
				if currentDialog == nil {
					continue
				}
				// 再次获得 answer，合并结果
				currentDialog.Answer.MessageContent = fmt.Sprintf("%s\n%s", currentDialog.Query.MessageContent, hitChat.GetMessage().GetText())
			}
		}
	}

	if currentDialog != nil && currentDialog.Query != nil && currentDialog.Answer != nil {
		result = append(result, currentDialog)
	}

	result = result[util.Max(0, len(result)-c.maxCount):]

	return result, nil
}

func genDialogRecord(scene string, roleType model.RoleType, senderId int64, message *proto.ChatMessage) *model.DialogRecord {
	return &model.DialogRecord{
		Scene:          scene,
		RoleType:       roleType.ToConvert(),
		MemberId:       senderId,
		MessageId:      message.GetMessageId(),
		MessageType:    int64(proto.ChatMessageType_TEXT),
		MessageContent: message.GetText(),
		RecordAt:       time.UnixMilli(message.GetTimestampMs()),
	}
}

func (c *DigitalAuthorChatHistoryLogic) realMergeUser(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], history []*message.DialogueWrapper) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "prepare.DigitalAuthorChatHistoryLogic.realMergeUser")
	defer span.Finish()

	requestCtx.GetBizContext().SetHistoryDialogue(history)

	return nil
}
