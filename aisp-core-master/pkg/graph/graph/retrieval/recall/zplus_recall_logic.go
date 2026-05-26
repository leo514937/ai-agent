package recall

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/entities_util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	util2 "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// @logicAuthor: wangran
// @logicInfo: 知+ 自维护召回队列
type ZplusRecallLogic struct {
	*logic.DefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item]
	zplusRpc rpc.AdPlatFormRPC
}

func NewZplusRecallLogic(name string, config map[string]string) *ZplusRecallLogic {
	res := &ZplusRecallLogic{
		DefaultRecallerDecorator: logic.NewDefaultRecallerDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.zplusRpc = impl.DefaultAdPlatformImpl
	res.RecallFunc = res.realRecall
	return res
}

func (z *ZplusRecallLogic) realRecall(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	startTime := time.Now().UnixMilli()
	resList := make([]*data_frame.ItemData[entities.Item], 0)
	skip := cast.ToBool(requestCtx.GetBizContext().GetLogicConfig(z.GetName(), conf.BaseConfigSkip))
	if skip {
		log.Infof(ctx, "logic execute skip: %s", z.GetName())
		return resList, nil
	}
	logicContext := logic_context.InitLogicContextV2BySource[[]*entities.Item](ctx, requestCtx, z.GetName(), logic_context.CacheSourceByTidb, "recall.ZplusRecallLogic.recall")
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

	topK := cast.ToInt(requestCtx.GetBizContext().GetLogicConfig(z.GetName(), conf.ConfigRecallSize))
	if topK <= 0 {
		return resList, nil
	}

	query := requestCtx.GetBizContext().RequestMessage().Text
	queryMerge := requestCtx.GetBizContext().GetQueryMergeText()
	memberId := requestCtx.GetBizContext().MemberId()
	sessionId := requestCtx.GetBizContext().GetSessionId()
	messageId := requestCtx.GetBizContext().RequestMessage().GetMessageId()
	recallItems := z.zplusRpc.GetRecallList(ctx, query, queryMerge, memberId, util.Int64String(sessionId), messageId, requestCtx.GetBizContext().GetBrandExternalInfo())

	for idx, recallItem := range recallItems {
		item := z.genItem(recallItem)
		item.GetItemMeta().GetRecallSourceInfo().RecallRank = idx + 1
		resList = append(resList, item.IntoFrameItem(requestCtx))
	}

	resList = resList[:util2.Min(topK, len(resList))]

	z.saveTracing(resList, startTime, requestCtx)
	return resList, nil
}

func (z *ZplusRecallLogic) genItem(recallItem *model.ItemMeta) *entities.Item {
	item := &entities.Item{
		TimestampMs:          time.Now().UnixMilli(),
		ChatTextTurnoverType: entities.ChatMappingTypeRecallChunk,
		Type:                 proto.ChatMessageType_TEXT,
		ItemMeta: &model.ItemMeta{
			DocId:   recallItem.DocId,
			DocType: recallItem.DocType,
			Raw:     recallItem.Raw,
			Content: recallItem.Raw,
			Title:   recallItem.Title,
			RecallSourceInfo: &model.RecallSourceInfo{
				IndexSource: conf.IndexSourceZhihu,
				KbSources:   []conf.KbSource{conf.KbSourceZPlusAutomotive},
			},
		},
		Security: &model.Security{},
	}

	return item
}

func (z *ZplusRecallLogic) saveTracing(outputItems []*data_frame.ItemData[entities.Item], startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:  z.GetName(),
		LogicInput: []string{},
		LogicOutput: lo.Map(outputItems, func(item *data_frame.ItemData[entities.Item], _ int) string {
			return item.GetBizItem().ToDescription()
		}),
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(z.GetName(), logicTracing)
}
