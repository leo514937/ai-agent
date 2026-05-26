package filter

import (
	"context"
	"fmt"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

const tagFilterReasonFmt = "tag_core_filter_%s"

// @logicAuthor: liupenghe
// @logicInfo: 召回过滤

type KbRecallTagFilterLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewKbRecallTagFilterLogic(name string, config map[string]string) *KbRecallTagFilterLogic {
	res := &KbRecallTagFilterLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.NeedFilterItemsFunc = res.needFilterItems
	return res
}

func (c *KbRecallTagFilterLogic) needFilterItems(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[*data_frame.ItemData[entities.Item]]string, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "filter.KbRecallTagFilterLogic.needFilterItems")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[*data_frame.ItemData[entities.Item]]string)

	// 获取 附加排除的召回类型
	extraExcludedKbSources := c.getFilterExtraExcludeKbSourceConfig(requestCtx)

	for _, item := range items {
		// 附加排除 当 IncludeDocType 和 ExtraExcludeKbSource 同时满足时 附加排除kbSource
		if item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ContainSources(extraExcludedKbSources) {
			continue
		}

		tagInfo := item.GetBizItem().GetItemMeta().TagInfo
		// 流量管控过滤
		if util.GetContentTrafficControlTagValue(tagInfo) == fmt.Sprintf("%d", rpc.TagCoreContentTrafficControlT2) {
			resMap[item] = fmt.Sprintf(tagFilterReasonFmt, rpc.TagCoreContentTrafficControl)
		}
		// 故事内容过滤
		if util.GetGeneralStoryTagValue(tagInfo) == rpc.TagCoreGeneralStory {
			resMap[item] = fmt.Sprintf(tagFilterReasonFmt, rpc.TagCoreGeneralStory)
		}
		// a1 内容过滤
		if util.GetContentSubjectiveLevelTagValue(tagInfo) == fmt.Sprintf("%d", rpc.TagCoreContentSubjectiveLevelA1) {
			resMap[item] = fmt.Sprintf(tagFilterReasonFmt, rpc.TagCoreContentSubjectiveLevel)
		}
		// aigc 内容过滤
		if util.GetMaybeCreatedByAITagValue(tagInfo) == rpc.TagCoreMaybeCreatedByAI {
			resMap[item] = fmt.Sprintf(tagFilterReasonFmt, rpc.TagCoreMaybeCreatedByAI)
		}
	}

	return resMap, nil
}

// getFilterExtraExcludeKbSourceConfig 获取过滤 排除召回类型
func (c *KbRecallTagFilterLogic) getFilterExtraExcludeKbSourceConfig(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) []conf.KbSource {
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
