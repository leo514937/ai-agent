package filter

import (
	"context"
	"fmt"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

const filterReasonFmt = "content_regulate_%s"

// @logicAuthor: wangran
// @logicInfo: 内容管控过滤
type ContentRegulateFilterLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewContentRegulateFilterLogic(name string, config map[string]string) *ContentRegulateFilterLogic {
	res := &ContentRegulateFilterLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.NeedFilterItemsFunc = res.needFilterItems
	return res
}

func (c *ContentRegulateFilterLogic) needFilterItems(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[*data_frame.ItemData[entities.Item]]string, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "filter.ContentRegulateFilterLogic.needFilterItems")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	filterInstructions := strings.Split(requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ConfigRegulateKey), ",")
	resMap := make(map[*data_frame.ItemData[entities.Item]]string)

	// 获取 附加排除的召回类型
	extraExcludedKbSources := c.getFilterExtraExcludeKbSourceConfig(requestCtx)

	for _, item := range items {
		// 附加排除 当 IncludeDocType 和 ExtraExcludeKbSource 同时满足时 附加排除kbSource
		if item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ContainSources(extraExcludedKbSources) {
			continue
		}

		for instruction, value := range item.GetBizItem().GetItemMeta().RegulateInfo {
			if util.StringInSlice(instruction, filterInstructions) && value == rpc.InstructionValueDisable {
				resMap[item] = fmt.Sprintf(filterReasonFmt, instruction)
			}
		}
	}

	return resMap, nil
}

// getFilterExtraExcludeKbSourceConfig 获取过滤 排除召回类型
func (c *ContentRegulateFilterLogic) getFilterExtraExcludeKbSourceConfig(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []conf.KbSource {
	filterLogicConfByExtraExcludeKbSourceStrArr := strings.Split(requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.FilterLogicConfByExtraExcludeKbSourceArr), ",")
	filterExtraExcludeKbSourceArr := make([]conf.KbSource, 0)
	for _, kbSourceStr := range filterLogicConfByExtraExcludeKbSourceStrArr {
		kbSource := conf.KbSource(kbSourceStr)
		if kbSource == "" {
			continue
		}
		filterExtraExcludeKbSourceArr = append(filterExtraExcludeKbSourceArr, kbSource)
	}
	return filterExtraExcludeKbSourceArr
}
