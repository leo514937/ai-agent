package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 获取站点召回domain等级（用于后续低质站点过滤）
// 需求文档：https://zhihu.kdocs.cn/l/cdMYeGOYtoDk

type OutSiteLevelMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, int]
	defLevel     int // 默认等级
	siteLevelDao dao.SiteLevelDao
}

func NewOutSiteLevelMetaFetcherLogic(name string, config map[string]string) *OutSiteLevelMetaFetcherLogic {
	res := &OutSiteLevelMetaFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, int](name, config),
	}
	res.defLevel = 3
	res.siteLevelDao = impl.NewSiteLevelDaoImpl()
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	return res
}

func (c *OutSiteLevelMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]int, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.ContentCoreMetaFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	logger := log.WithFields(ctx, map[string]any{
		"func": "OutSiteLevelMetaFetcherLogic-fetch",
	})
	logger.Debugf(ctx, "do running")

	if items == nil || len(items) == 0 {
		return map[data_frame.UniqueId]int{}, nil
	}

	urlArray := make([]string, 0)
	resMap := make(map[data_frame.UniqueId]int)
	syncMap := util.NewSyncMap[data_frame.UniqueId, int]()
	wg := safe_group.NewGroup("GetRandomPrefabWordByRedis")
	for _, contentItem := range items {
		if contentItem.GetBizItem().GetItemMeta().Url != "" {
			urlArray = append(urlArray, contentItem.GetBizItem().GetItemMeta().Url)
		}
		wg.Go(func() error {
			domainInfo, err := util.ExtractDomainInfo(contentItem.GetBizItem().GetItemMeta().Url)
			if err != nil {
				logger.Errorf(ctx, "extract domain error: %v", err)
				return err
			}

			// 查询缓存
			siteLevelMap, daoErr := c.siteLevelDao.GetLevelWithDefault(ctx, -1, domainInfo.FullDomain, domainInfo.RootDomain)
			if daoErr != nil {
				logger.Errorf(ctx, "get domain cache error: %v", err)
				return err
			}

			level := siteLevelMap[domainInfo.FullDomain]
			if level == -1 {
				if rootLevel, isExist := siteLevelMap[domainInfo.RootDomain]; isExist && rootLevel != -1 {
					level = rootLevel
				} else {
					level = c.defLevel
				}
			}
			key := *data_frame.NewUniqueId(contentItem.GetCommonItem().Id())
			syncMap.Set(key, level)
			return nil
		})
	}
	waitError := wg.Wait()
	if waitError != nil {
		logger.Errorf(ctx, "waitError => %s", waitError)
	}

	syncMap.Range(func(key data_frame.UniqueId, value int) bool {
		resMap[key] = value
		return true
	})

	constant.DataInputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(urlArray))
	constant.DataOutputNodeLog.Infof(logCtx, "%s", util.GetJSONIgnoreError(resMap))
	return resMap, nil
}

func (c *OutSiteLevelMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], level int) error {
	item.GetBizItem().GetItemMeta().SiteLevel = level
	return nil
}
