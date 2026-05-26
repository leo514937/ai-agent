package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type ParentContentCoreMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, *base.ContentInfo]
	contentCoreRpc rpc.ContentCoreRPC
}

func NewParentContentCoreMetaFetcherLogic(name string, config map[string]string) *ParentContentCoreMetaFetcherLogic {
	res := &ParentContentCoreMetaFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, *base.ContentInfo](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.contentCoreRpc = impl.DefaultContentCoreRPCImpl
	return res
}

func (c *ParentContentCoreMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*base.ContentInfo, error) {
	if items == nil || len(items) == 0 {
		return map[data_frame.UniqueId]*base.ContentInfo{}, nil
	}

	resMap := make(map[data_frame.UniqueId]*base.ContentInfo)
	itemMap := make(map[*data_frame.ItemData[entities.Item]]string)
	contents := make([]string, 0)
	for _, contentItem := range items {
		itemContentInfo := contentItem.GetBizItem().GetItemMeta().ContentInfo
		if itemContentInfo == nil {
			continue
		}
		if itemContentInfo.GetExtInfo() != nil && itemContentInfo.GetExtInfo().GetParentInfo() != nil &&
			itemContentInfo.GetExtInfo().GetParentInfo().ContentID != "" {
			contentId := itemContentInfo.GetExtInfo().GetParentInfo().ContentID
			contents = append(contents, contentId)
			itemMap[contentItem] = contentId
		}
	}

	// 查询内容 url token
	contentResultMap := c.contentCoreRpc.BatchGetContentByContentID(ctx, contents,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentBody)

	//	获取内容 ContentCoreInfo
	for item, parentContentId := range itemMap {
		contentInfo, isOk := contentResultMap[parentContentId]
		if !isOk {
			continue
		}

		resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = contentInfo
	}
	return resMap, nil
}

func (c *ParentContentCoreMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *base.ContentInfo) error {
	if res == nil {
		return nil
	}

	item.GetBizItem().GetItemMeta().ParentContentInfo = res
	return nil
}
