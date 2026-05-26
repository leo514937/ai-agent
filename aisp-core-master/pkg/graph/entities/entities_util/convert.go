package entities_util

import (
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

func DataFrameList2ItemList(dataFrameList *[]*data_frame.ItemData[entities.Item]) *[]*entities.Item {
	items := make([]*entities.Item, 0)
	for _, frame := range *dataFrameList {
		items = append(items, frame.GetBizItem())
	}
	return &items
}
func DataFrameList2ItemListAndPush(dataFrameList *[]*data_frame.ItemData[entities.Item], itemsPoint *[]*entities.Item) {
	for _, frame := range *dataFrameList {
		*itemsPoint = append(*itemsPoint, frame.GetBizItem())
	}
}

func ItemList2DataFrameList(items *[]*entities.Item, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) *[]*data_frame.ItemData[entities.Item] {
	dataFrameList := make([]*data_frame.ItemData[entities.Item], 0)
	for _, item := range *items {
		dataFrameList = append(dataFrameList, item.IntoFrameItem(requestCtx))
	}
	return &dataFrameList
}
func ItemList2DataFrameListAndPush(items *[]*entities.Item, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], dataFrameListPoint *[]*data_frame.ItemData[entities.Item]) {
	for _, item := range *items {
		*dataFrameListPoint = append(*dataFrameListPoint, item.IntoFrameItem(requestCtx))
	}
}
