package filter

import (
	"context"
	"fmt"

	apollo "git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: wangran
// @logicInfo: 黑名单召回内容过滤

const recallBlacklistReason = "recall_blacklist"

type KbRecallBlackListFilterLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewKbRecallBlackListFilterLogic(name string, config map[string]string) *KbRecallBlackListFilterLogic {
	res := &KbRecallBlackListFilterLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.NeedFilterItemsFunc = res.needFilterItems
	return res
}

func (c *KbRecallBlackListFilterLogic) needFilterItems(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[*data_frame.ItemData[entities.Item]]string, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "filter.KbRecallSiteLevelFilterLogic.needFilterItems")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	// 召回黑名单，格式为：docType.String()-docId,docType.String()-url,
	blackRecallDocStrings := apollo.GetStringArray(macro.RecallBlackListConfigName, ",", []string{})

	resMap := make(map[*data_frame.ItemData[entities.Item]]string)
	for _, item := range items {
		itemIdKey := fmt.Sprintf("%s-%d", item.GetBizItem().GetItemMeta().DocType.String(), item.GetBizItem().GetItemMeta().DocId)
		itemUrlKey := fmt.Sprintf("%s-%s", item.GetBizItem().GetItemMeta().DocType.String(), item.GetBizItem().GetItemMeta().Url)
		if util.StringInSlice(itemIdKey, blackRecallDocStrings) || util.StringInSlice(itemUrlKey, blackRecallDocStrings) {
			resMap[item] = recallBlacklistReason
		}
	}

	return resMap, nil
}
