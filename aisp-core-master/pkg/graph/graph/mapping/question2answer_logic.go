package mapping

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// Question2AnswerLogic 将 question 映射成其下第一个 answer
type Question2AnswerLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewQuestion2AnswerLogic(name string, config map[string]string) *Question2AnswerLogic {
	res := &Question2AnswerLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.realMapping
	return res
}

func (q *Question2AnswerLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "mapping.MultiChatSummaryLogic.realMapping")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	startTime := time.Now().UnixMilli()
	result := make([]*data_frame.ItemData[entities.Item], 0)
	if items == nil || len(items) == 0 {
		return result, nil
	}

	for _, item := range items {
		itemMeta := item.GetBizItem().GetItemMeta()
		if itemMeta.DocType == content.DocType_Question {
			if itemMeta.ContentInfo != nil && len(itemMeta.ChildContentInfo) > 0 {
				// 新建一个 answer 的结果
				answerContentInfo := itemMeta.ChildContentInfo[0]
				if answerContentInfo.GetContentBody() == nil {
					continue
				}
				body := answerContentInfo.GetContentBody().GetBody()
				filteredBody, _ := util.ContentHtml2Markdown(ctx, body)

				newItem := &entities.Item{
					TimestampMs:          time.Now().UnixMilli(),
					ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
					Type:                 proto.ChatMessageType_TEXT,
					ItemMeta: &model.ItemMeta{
						DocId:             cast.ToInt64(answerContentInfo.GetOutID()),
						DocType:           model.GetDocType(answerContentInfo.ContentType),
						Title:             itemMeta.ContentInfo.GetTitle(),
						Content:           filteredBody,
						IndexDocUniqueId:  itemMeta.IndexDocUniqueId,
						Abstract:          util.UnicodeSubstr(filteredBody, 0, macro.CardAbstractLimit),
						PublishedTime:     answerContentInfo.GetPublished(),
						RecallSourceInfo:  itemMeta.GetRecallSourceInfo(),
						ContentInfo:       answerContentInfo,
						ParentContentInfo: itemMeta.ContentInfo,
					},
				}
				result = append(result, newItem.IntoFrameItem(requestCtx))
			}
		} else {
			result = append(result, item)
		}
	}

	q.saveTracing(items, result, startTime, requestCtx)
	return result, nil
}

func (q *Question2AnswerLogic) saveTracing(inputItems []*data_frame.ItemData[entities.Item], outputItems []*data_frame.ItemData[entities.Item], startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName: q.GetName(),
		LogicInput: lo.Map(inputItems, func(item *data_frame.ItemData[entities.Item], _ int) string {
			return item.GetBizItem().ToDescription()
		}),
		LogicOutput: lo.Map(outputItems, func(item *data_frame.ItemData[entities.Item], _ int) string {
			return item.GetBizItem().ToDescription()
		}),
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(q.GetName(), logicTracing)
}
