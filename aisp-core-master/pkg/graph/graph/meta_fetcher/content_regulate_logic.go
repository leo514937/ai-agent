package meta_fetcher

import (
	"context"

	content2 "git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// @logicAuthor: wangran
// @logicInfo: 内容管控信息获取

type ContentRegulateLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]string]
	CiClient        rpc.ContentRegulateRPC
	excludeDocTypes []content2.DocType_Type
}

func NewContentRegulateLogic(name string, config map[string]string) *ContentRegulateLogic {
	res := &ContentRegulateLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, map[string]string](name, config),
	}
	res.excludeDocTypes = []content2.DocType_Type{content2.DocType_Unknown, content2.DocType_Member, content2.DocType_Text, content2.DocType_Link}
	res.CiClient = impl.DefaultContentRegulateRPCImpl
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	return res
}

func (c *ContentRegulateLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]map[string]string, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.ContentRegulateLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	sceneCode := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ConfigRegulateSceneCode)
	subSceneCode := requestCtx.GetBizContext().GetLogicConfig(c.GetName(), conf.ConfigRegulateSubSceneCode)

	// 获取 过滤白名单配置
	filterIncludeDocTypeArr, filterIncludePaperArr := util.GetFilterIncludeTypeConfig(c.Name, requestCtx)

	resMap := make(map[data_frame.UniqueId]map[string]string)

	var contents []model.Content
	for _, item := range items {
		// 过滤白名单
		hitFilterWhiteList := item.GetBizItem().IsHitFilterWhiteList(filterIncludeDocTypeArr, filterIncludePaperArr)
		if !hitFilterWhiteList {
			continue
		}

		docId := item.GetBizItem().GetItemMeta().DocId
		docType := item.GetBizItem().GetItemMeta().DocType

		// 排除一些站内内容 和 站外内容
		if docId != 0 && !lo.Contains(c.excludeDocTypes, docType) {
			contents = append(contents, model.NewContentWithDocType(docId, docType))
		}
	}

	if len(contents) == 0 {
		return resMap, nil
	}

	contentInstruction := c.CiClient.BatchGetValidInstruction(ctx, sceneCode, subSceneCode, contents)

	for _, item := range items {
		content := model.NewContentWithDocType(item.GetBizItem().GetItemMeta().DocId, item.GetBizItem().GetItemMeta().DocType)
		if instruction, exist := contentInstruction[content]; exist {
			resMap[*data_frame.NewUniqueId(item.GetCommonItem().Id())] = instruction
		}
	}

	constant.DataOutputNodeLog.Infof(logCtx, "%v", contentInstruction)

	return resMap, nil
}

func (c *ContentRegulateLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res map[string]string) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "meta_fetcher.ContentRegulateLogic.itemMerge")
	defer span.Finish()

	item.GetBizItem().GetItemMeta().RegulateInfo = res
	return nil
}
