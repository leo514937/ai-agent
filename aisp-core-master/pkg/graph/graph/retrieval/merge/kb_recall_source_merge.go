package merge

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/entities_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"github.com/samber/lo"

	//"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: wangran
// @logicInfo: 召回队列合并去重
// @logicOutput: 0 | 召回结果。[]*data_frame.ItemData[entities.Item]

type KbRecallSourceMergeLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewKbRecallSourceMergeLogic(name string, config map[string]string) *KbRecallSourceMergeLogic {
	res := &KbRecallSourceMergeLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.realMerge
	return res
}

func (i *KbRecallSourceMergeLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	respItems := make([]*data_frame.ItemData[entities.Item], 0)
	logicContext := logic_context.InitLogicContextV2BySource[[]*entities.Item](ctx, requestCtx, i.GetName(), logic_context.CacheSourceByTidb, "recall.KbRecallSourceMergeLogic.realMerge")
	ctx = logicContext.Ctx
	logCtx := logicContext.LogCtx
	defer func() {
		logicContext.DeferFunc(entities_util.DataFrameList2ItemList(&respItems))
	}()
	// 如果有缓存 直接返回，直接返回
	if logicContext.CacheResp.IsOk && logicContext.CacheResp.Resp != nil && len(logicContext.CacheResp.Resp) > 0 {
		// data_frame 有些内部参数无法序列化，所以需要重新创建一下 item
		entities_util.ItemList2DataFrameListAndPush(&logicContext.CacheResp.Resp, requestCtx, &respItems)
		return respItems, nil
	}

	itemList := lo.Flatten(itemLists)
	respItems = entities.ItemListMergeDuplicate(itemList)

	constant.DataInputNodeLog.Infof(logCtx, "inputSize:%s", len(itemList))
	constant.DataOutputNodeLog.Infof(logCtx, "outputSize:%s", len(respItems))

	if requestCtx.GetBizContext().GetIsTest() {
		requestCtx.DataMap().SetObjMap(logCtx, i.GetOutputName(0), respItems)
	}

	i.saveOriginalRecallTracing(logCtx, respItems, requestCtx)
	requestCtx.GetBizContext().SetRecallItems(lo.Map(respItems, func(item *data_frame.ItemData[entities.Item], _ int) *entities.Item {
		return item.GetBizItem()
	}))
	return respItems, nil
}

func (i *KbRecallSourceMergeLogic) saveOriginalRecallTracing(logCtx context.Context, recallItems []*data_frame.ItemData[entities.Item], requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	// 记录原始召回
	var recallIndexTracing []*proto.IndexTracing
	for _, item := range recallItems {
		recallIndexTracing = append(recallIndexTracing, i.item2IndexTracing(item))
	}
	requestCtx.GetBizContext().Tracing().ProcessTracing.OriginalRecallItem = recallIndexTracing

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(recallIndexTracing))
}

func (i *KbRecallSourceMergeLogic) item2IndexTracing(item *data_frame.ItemData[entities.Item]) *proto.IndexTracing {
	itemMeta := item.GetBizItem().GetItemMeta()

	return &proto.IndexTracing{
		DocId:   itemMeta.DocId,
		DocType: util.DocType2ContentType(itemMeta.DocType),
		Title:   item.GetBizItem().GetItemMeta().GetContentTitle(),
		Url:     itemMeta.Url,
		Text:    util.UnicodeSubstr(itemMeta.Content, 0, 50),
		RecallInfo: []*proto.RecallInfo{{
			RecallSource: util.GetJSONIgnoreError(itemMeta.GetRecallSourceInfo()),
			RecallScore:  itemMeta.GetRecallSourceInfo().RecallScore,
			IsUsed:       true,
		}},
		PublishTime: itemMeta.PublishedTime,
	}
}
