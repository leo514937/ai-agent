package recall

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/entities_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 同问题下回答召回，在原有召回队列结果上追加
type KbSameQuestionAnswerAppendLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
	contentCoreRpc rpc.ContentCoreRPC
	metis2Rpc      rpc.Metis2Rpc
}

func NewKbSameQuestionAnswerAppendLogic(name string, config map[string]string) *KbSameQuestionAnswerAppendLogic {
	res := &KbSameQuestionAnswerAppendLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.contentCoreRpc = impl.DefaultContentCoreRPCImpl
	res.metis2Rpc = impl.DefaultMetis2RPCImpl
	res.MappingFunc = res.realMapping
	return res
}

func (k *KbSameQuestionAnswerAppendLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	startTime := time.Now().UnixMilli()
	resList := make([]*data_frame.ItemData[entities.Item], 0)
	logicContext := logic_context.InitLogicContextV2BySource[[]*entities.Item](ctx, requestCtx, k.GetName(), logic_context.CacheSourceByTidb, "recall.RumLogic.recall")
	ctx = logicContext.Ctx
	defer func() {
		logicContext.DeferFunc(entities_util.DataFrameList2ItemList(&resList))
	}()
	// 如果有缓存 直接返回，直接返回
	if logicContext.CacheResp.IsOk && logicContext.CacheResp.Resp != nil && len(logicContext.CacheResp.Resp) > 0 {
		// data_frame 有些内部参数无法序列化，所以需要重新创建一下 item
		entities_util.ItemList2DataFrameListAndPush(&logicContext.CacheResp.Resp, requestCtx, &resList)
		return resList, nil
	}

	// 每个 answer 召回其 question 下威尔逊排序的 topK 个其他 answer
	topK := cast.ToInt32(requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallSameQuestionAnswerTopK))
	if topK == 0 {
		return items, nil
	}

	// 查询内容 meta 信息，获取其 questionId
	var questionIds []int64
	contents := lo.Map(items, func(item *data_frame.ItemData[entities.Item], _ int) model.Content {
		return model.Content{
			ContentID:   item.GetBizItem().GetItemMeta().DocId,
			ContentType: item.GetBizItem().GetItemMeta().DocType,
		}
	})
	contentResultMap := k.contentCoreRpc.BatchGetContent(ctx, contents, base.ContentInfoFieldContentExtInfo)
	for _, itemContentInfo := range contentResultMap {
		if itemContentInfo.GetExtInfo() != nil && itemContentInfo.GetExtInfo().GetParentInfo() != nil && itemContentInfo.GetExtInfo().GetParentInfo().GetContentType() == content_core_thrift.ContentTypeQuestion {
			questionIds = append(questionIds, cast.ToInt64(itemContentInfo.GetExtInfo().GetParentInfo().OutID))
		}
	}

	// 从 questionId 到 answerId
	questionAnswerIdMap := k.metis2Rpc.ConcurrentGetQuestionAnswerIds(ctx, questionIds, topK, 10)
	for _, answerIds := range questionAnswerIdMap {
		for _, answerId := range answerIds {
			items = append(items, k.genItem(answerId, content.DocType_Answer).IntoFrameItem(requestCtx))
		}
	}

	k.saveTracing(items, startTime, requestCtx)
	return items, nil
}

func (k *KbSameQuestionAnswerAppendLogic) genItem(docId int64, docType content.DocType_Type) *entities.Item {
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		Text:                 "",
		ItemMeta: &model.ItemMeta{
			DocId:   docId,
			DocType: docType,
			RecallSourceInfo: &model.RecallSourceInfo{
				IndexSource: conf.IndexSourceZhihu,
				KbSources:   []conf.KbSource{conf.KbSourceZhihuSameQuestionAnswer},
			},
		},
		Security: &model.Security{},
	}

	return item
}

func (k *KbSameQuestionAnswerAppendLogic) saveTracing(outputItems []*data_frame.ItemData[entities.Item], startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:  k.GetName(),
		LogicInput: []string{},
		LogicOutput: lo.Map(outputItems, func(item *data_frame.ItemData[entities.Item], _ int) string {
			return item.GetBizItem().ToDescription()
		}),
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(k.GetName(), logicTracing)
}
