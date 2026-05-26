package filter

import (
	"context"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/filter"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

const filterReason = "author_sign_blacklist"

// IndexDeleteFilterLogic 用户主动删除索引后过滤算子，用于 zsearch 这类非自建索引
type IndexDeleteFilterLogic struct {
	*filter.FilterLogic[entities.RequestContext, entities.User, entities.Item]
	redisDao dao.DigitalAuthorIndexDao
}

func NewIndexDeleteFilterLogic(name string, config map[string]string) *IndexDeleteFilterLogic {
	res := &IndexDeleteFilterLogic{
		FilterLogic: filter.NewFilterLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.redisDao = impl.DefaultFeatureUsageInfoDaoImpl
	res.NeedFilterItemsFunc = res.needFilterItems
	return res
}

func (i *IndexDeleteFilterLogic) needFilterItems(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[*data_frame.ItemData[entities.Item]]string, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "filter.IndexDeleteFilterLogic.needFilterItems")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[*data_frame.ItemData[entities.Item]]string)

	for _, item := range items {
		docId := item.GetBizItem().GetItemMeta().DocId
		docType := item.GetBizItem().GetItemMeta().DocType

		// 非 doc 不做过滤
		if docId == 0 || docType == content.DocType_Unknown {
			continue
		}

		res, err := i.redisDao.GetOnSiteIndexStatus(ctx, docId, docType)

		// 没有存储记录，不做过滤
		if err != nil {
			continue
		}

		// 用户主动标记黑名单
		if res == false {
			resMap[item] = filterReason
		}

	}

	return resMap, nil
}
