package filter

import (
	"context"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	content2 "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 空内容过滤
type EmptyMetaFilterLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
	excludeDocTypes []content2.DocType_Type
}

func NewEmptyMetaFilterLogic(name string, config map[string]string) *EmptyMetaFilterLogic {
	res := &EmptyMetaFilterLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.excludeDocTypes = []content2.DocType_Type{content2.DocType_Unknown, content2.DocType_Member, content2.DocType_Text, content2.DocType_Link, content2.DocType_InternalDoc, content2.DocType_AispUserUpload}
	res.NeedFilterItemsFunc = res.needFilterItems
	return res
}

func (e *EmptyMetaFilterLogic) needFilterItems(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[*data_frame.ItemData[entities.Item]]string, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "filter.ContentRegulateFilterLogic.needFilterItems")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))
	startTime := time.Now().UnixMilli()

	resMap := make(map[*data_frame.ItemData[entities.Item]]string)

	for _, item := range items {
		// 排除一些站内内容 和 站外内容
		if lo.Contains(e.excludeDocTypes, item.GetBizItem().GetItemMeta().DocType) {
			continue
		}
		if item.GetBizItem().GetItemMeta().ContentInfo == nil {
			resMap[item] = "empty_meta"
		}
	}

	e.saveTracing(resMap, startTime, requestCtx)
	return resMap, nil
}

func (e *EmptyMetaFilterLogic) saveTracing(response map[*data_frame.ItemData[entities.Item]]string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	respStr := lo.Map(lo.Keys(response), func(item *data_frame.ItemData[entities.Item], _ int) string {
		return item.GetBizItem().ToDescription()
	})
	logicTracing := &proto.LogicTracing{
		LogicName:   e.GetName(),
		LogicInput:  []string{},
		LogicOutput: respStr,
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(e.GetName(), logicTracing)
}
