package main

import (
	"context"
	"fmt"

	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
)

func main() {

	items := []*entities.Item{
		{
			Text: "item1",
			ItemMeta: &model.ItemMeta{
				Content: "content1",
				DocId:   111,
				DocType: content.DocType_Answer,
			},
		},
		{
			Text: "item2",
			ItemMeta: &model.ItemMeta{
				Content: "content2",
				DocId:   222,
				DocType: content.DocType_Article,
			},
		},
		{
			Text: "item3",
			ItemMeta: &model.ItemMeta{
				Content: "content3",
				DocId:   333,
				DocType: content.DocType_Answer,
			},
		},
		{
			Text: "item4",
			ItemMeta: &model.ItemMeta{
				Content: "content4",
				DocId:   444,
				DocType: content.DocType_Answer,
			},
		},
	}

	ctx := context.Background()
	cacheDao := impl.NewLogicSessionCacheDao[[]*entities.Item]()

	fmt.Println("存储缓存 ----")
	saveErr := cacheDao.SaveCache(ctx, "TestScene", "TestLogic", 123, &items)
	if saveErr == nil {
		fmt.Println("存储缓存 ---- 成功")

	}

	fmt.Println("获取缓存 ----")
	itemList, _ := cacheDao.GetCache(ctx, "TestScene", "TestLogic", 123)
	for _, item := range *itemList {
		fmt.Println(util.GetJSONIgnoreError(item))
	}
	fmt.Println("删除缓存 ----")
	removeErr := cacheDao.RemoveCache(ctx, "TestScene", "TestLogic", 123)
	if removeErr == nil {
		fmt.Println("删除缓存 ---- 成功")

	}

}
