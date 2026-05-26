package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-user_core/user_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

type AuthorInfoFetchLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, *user_core_thrift.User]
	userCoreRpc rpc.UserCoreService
}

func NewAuthorInfoFetchLogic(name string, config map[string]string) *AuthorInfoFetchLogic {
	res := &AuthorInfoFetchLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, *user_core_thrift.User](name, config),
	}
	res.userCoreRpc = impl.DefaultUserCoreServiceImpl
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	return res
}

func (a *AuthorInfoFetchLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*user_core_thrift.User, error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.ChunkExistFetchLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	resMap := make(map[data_frame.UniqueId]*user_core_thrift.User)

	var authorIds []int64
	for _, item := range items {
		authorId := item.GetBizItem().GetItemMeta().AuthorId
		if authorId != 0 {
			authorIds = append(authorIds, authorId)
		}
	}
	authorIds = lo.Uniq(authorIds)

	authorInfoMap, err := a.userCoreRpc.BatchGetUserByIds(ctx, authorIds, []string{user_core_thrift.ProfileField})
	if err != nil {
		return nil, err
	}

	for _, item := range items {
		authorId := item.GetBizItem().GetItemMeta().AuthorId
		if authorInfo, exist := authorInfoMap[authorId]; exist {
			resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = authorInfo
		}
	}

	return resMap, nil
}

func (a *AuthorInfoFetchLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *user_core_thrift.User) error {
	item.GetBizItem().GetItemMeta().AuthorName = res.GetProfile().GetFullname()
	return nil
}
