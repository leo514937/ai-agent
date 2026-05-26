package generate

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	router_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/tidwall/gjson"
)

type DirectChatLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewDirectChatLogic(name string, config map[string]string) *DirectChatLogic {
	res := &DirectChatLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.handler
	return res
}

func (q *DirectChatLogic) handler(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "DirectChatLogic.realMerge")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	items := lo.Flatten(itemLists)

	toolInfo := requestCtx.GetBizContext().GetToolInfo()
	if toolInfo != nil {
		switch toolInfo.Name {
		// 越狱
		case router_macro.RouterAgentByJailbreak.String():
			arguments := gjson.Parse(toolInfo.Arguments)
			if arguments.Get("reply").Exists() {
				item := entities.ItemFromMessageByAnswerAndType(&proto.ChatMessage{
					MessageId:   requestCtx.GetBizContext().RespMessageId(),
					TimestampMs: time.Now().UnixMilli(),
					Type:        proto.ChatMessageType_TEXT,
					Text:        arguments.Get("reply").String(),
				}, proto.ChatRespType_UNANSWERABLE)
				items = append(items, item.IntoFrameItem(requestCtx))
			}
		// 意图澄清
		case router_macro.RouterAgentByClarify.String():
			arguments := gjson.Parse(toolInfo.Arguments)
			if arguments.Get("clarification").Exists() {
				item := entities.ItemFromMessageByAnswerAndType(&proto.ChatMessage{
					MessageId:   requestCtx.GetBizContext().RespMessageId(),
					TimestampMs: time.Now().UnixMilli(),
					Type:        proto.ChatMessageType_TEXT,
					Text:        arguments.Get("clarification").String(),
				}, proto.ChatRespType_PLAIN_TEXT)
				items = append(items, item.IntoFrameItem(requestCtx))
			}
		}
	}
	return items, nil
}
