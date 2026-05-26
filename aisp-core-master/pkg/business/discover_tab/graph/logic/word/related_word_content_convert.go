package word

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 处理转换数据（伪装知乎召回内容时 转换Content到Text字段上）

// RelatedWordContentCovertLogic 相关词 拆解请求信息为知乎站内内容
type RelatedWordContentCovertLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	maxLen int
}

func NewRelatedWordContentCovertLogic(name string, config map[string]string) *RelatedWordContentCovertLogic {
	res := &RelatedWordContentCovertLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.maxLen = 1024
	res.MappingFunc = res.doHandle
	return res
}

func (l *RelatedWordContentCovertLogic) doHandle(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "word.RelatedWordContentCovertLogic.doHandle")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	filterItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk &&
			item.GetBizItem().GetItemMeta() != nil
	})

	// 处理转化数据
	for _, item := range filterItems {
		item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used = true

		// contentText 最大保留 8192 长度
		contentText := item.GetBizItem().GetItemMeta().Content
		if util.UnicodeLen(contentText) > l.maxLen {
			contentText = util.UnicodeSubstr(contentText, 0, l.maxLen)
		}
		item.GetBizItem().Text = contentText
	}

	// 如果docType 是 answer ，需要把 question 的标题 作为用户的query
	if len(filterItems) == 1 &&
		filterItems[0].GetBizItem().GetItemMeta().DocType == content.DocType_Answer &&
		filterItems[0].GetBizItem().GetItemMeta().ParentContentInfo != nil &&
		filterItems[0].GetBizItem().GetItemMeta().ParentContentInfo.GetTitle() != "" {
		chatMessage := &proto.ChatMessage{
			Text: filterItems[0].GetBizItem().GetItemMeta().ParentContentInfo.GetTitle(),
		}
		requestCtx.GetBizContext().GetCurrentDialogue().Query = entities.NewQueryDialogFormQuery(&proto.RequestInfo{
			Message: chatMessage,
		}, requestCtx.GetBizContext().GetBizType())
		requestCtx.GetBizContext().GetCurrentDialogue().Answer = l.getAnswerDialog(requestCtx, chatMessage.GetText(), chatMessage.GetMessageId())
		filterItems = append(filterItems, entities.ItemFromMessage(chatMessage).IntoFrameItem(requestCtx))
	}
	return filterItems, nil
}

// 组装 answer dialog
func (l *RelatedWordContentCovertLogic) getAnswerDialog(
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	answerText string, queryId string) *model.DialogRecord {
	// 创建answer dialog
	answerDialog := entities.NewAnswerDialogFormProtoChatRequest(
		requestCtx.GetBizContext(), answerText, model.DialogCreateTypeLLM, model.DialogErrorTypeNormal)
	answerDialog.ParentMessageId = queryId
	answerDialog.MessageGroupId = queryId
	return answerDialog
}
