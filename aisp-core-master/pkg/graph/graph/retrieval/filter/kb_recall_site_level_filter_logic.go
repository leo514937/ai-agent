package filter

import (
	"context"
	"fmt"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

const siteLevelFilterReasonFmt = "site_level_filter_%s"

// @logicAuthor: zhoupengcheng
// @logicInfo: 站点低质量 等级过滤
// 需求文档：https://zhihu.kdocs.cn/l/cdMYeGOYtoDk

type KbRecallSiteLevelFilterLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
	defThreshold int
}

func NewKbRecallSiteLevelFilterLogic(name string, config map[string]string) *KbRecallSiteLevelFilterLogic {
	res := &KbRecallSiteLevelFilterLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.defThreshold = 3
	res.NeedFilterItemsFunc = res.needFilterItems
	return res
}

func (c *KbRecallSiteLevelFilterLogic) needFilterItems(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[*data_frame.ItemData[entities.Item]]string, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "filter.KbRecallSiteLevelFilterLogic.needFilterItems")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	// 过滤低于level阈值的召回
	threshold := cast.ToInt(requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.RecallFilterSiteLevelThreshold.ToConvert()))
	if threshold <= 0 {
		threshold = c.defThreshold
	}

	resMap := make(map[*data_frame.ItemData[entities.Item]]string)
	for _, item := range items {
		// 只过滤 url
		if item.GetBizItem().GetItemMeta().DocType != content.DocType_Link {
			continue
		}

		// 过滤小于阈值的站点
		if item.GetBizItem().GetItemMeta().SiteLevel < threshold {
			resMap[item] = fmt.Sprintf(siteLevelFilterReasonFmt, cast.ToString(threshold))
		}
	}

	return resMap, nil
}
