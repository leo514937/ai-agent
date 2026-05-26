package response

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// BuildResponseLogic 构造返回结构体
// @logicAuthor: wanghao11
// @logicInfo: 构造返回结构体
// @logicOutput: 0 | 相关query，[]*proto.Query
// @logicOutput: 1 | dialogAnswer，*model.DialogRecord
type BuildResponseLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewBuildResponseLogic(name string, config map[string]string) *BuildResponseLogic {
	res := &BuildResponseLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.buildResponse
	res.NeedSignal = true
	return res
}

func (b *BuildResponseLogic) buildResponse(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "resp.BuildResponseLogic.buildResponse")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	log.Infof(ctx, "BuildResponseLogic buildResponse user: %+v itemLists: %+v", user, itemLists)

	// 避免空list，先做合并
	itemList := lo.Flatten(itemLists)
	// 补偿处理 如果上游没有传入answer 且 上下文中已经保存了answer，为了不影响下游逻辑，需要补偿到itemList中
	streamChatItems, isOk := requestCtx.GetCommonContext().GetLogicData(conf.StreamChatResultStoreKey.String()).([]*data_frame.ItemData[entities.Item])
	if isOk && streamChatItems != nil && len(streamChatItems) > 0 {
		itemList = append(itemList, streamChatItems...)
	}
	itemList = lo.UniqBy(itemList, func(item *data_frame.ItemData[entities.Item]) int64 {
		return item.GetCommonItem().Id().GetId()
	})

	bizCtx := requestCtx.GetBizContext()
	var responseRelevantQueryList = make([]*proto.Query, 0)
	// 处理返回内容，分别存放，AppendResponseItem 用于最终返回，其余用于附加返回与 tracing
	for _, item := range itemList {
		bizItem := item.GetBizItem()
		//	相关query
		if bizItem.ChatTextTurnoverType == entities.ChatMappingTypeQuestion {
			responseRelevantQueryList = append(responseRelevantQueryList, bizItem.ToQuery())
		} else if bizItem.ChatTextTurnoverType == entities.ChatMappingTypeLLMAnswer {
			// chat 回答
			bizCtx.AppendResponseItem(bizItem)
		}
		// 处理answer（如果answer还为空 则在最后 resp 补偿存入context）
		if bizItem.ChatTextTurnoverType == entities.ChatMappingTypeLLMAnswer {
			currentDialogue := bizCtx.GetCurrentDialogue()
			if currentDialogue.Answer == nil || currentDialogue.Answer.MessageId == "" {
				errType := model.DialogErrorTypeNormal
				if !bizItem.GetSecurity().IsSecurityAllPassed() {
					errType = model.DialogErrorTypeSecurityCover
				}

				dialogAnswerRecord := entities.NewAnswerDialogFormProtoChatRequest(
					bizCtx, bizItem.Text, model.DialogCreateTypeLLM, errType)
				bizCtx.SetCurrentDialogueByAnswer(dialogAnswerRecord)
			}
		}
	}

	requestCtx.DataMap().SetObjMap(logCtx, b.GetOutputName(0), responseRelevantQueryList)
	requestCtx.DataMap().SetObjMap(logCtx, b.GetOutputName(1), bizCtx.GetCurrentDialogue().Answer)

	return itemList, nil
}
