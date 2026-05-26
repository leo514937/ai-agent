package meta_fetcher

import (
	"context"
	"fmt"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/spf13/cast"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 站外内容 meta 抓取

type OutsideContentProdMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, *rpc.CurlRespInfo]
	contentProdRpc rpc.ContentProdRPC
}

func NewOutsideContentProdMetaFetcherLogic(name string, config map[string]string) *OutsideContentProdMetaFetcherLogic {
	res := &OutsideContentProdMetaFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, *rpc.CurlRespInfo](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.contentProdRpc = impl.NewContentProdRPCImpl()
	return res
}

func (c *OutsideContentProdMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId]*rpc.CurlRespInfo, error) {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "meta_fetcher.ContentCoreMetaFetcherLogic.fetch")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallOutSite2ZhihuMetaFetcherLogic-realRecallConvert",
	})
	logger.Debugf(ctx, "do running")

	if items == nil || len(items) == 0 {
		return map[data_frame.UniqueId]*rpc.CurlRespInfo{}, nil
	}

	resMap := make(map[data_frame.UniqueId]*rpc.CurlRespInfo)
	outsideUrls := make([]string, 0)
	outsideMap := make(map[string]*data_frame.ItemData[entities.Item])
	for _, contentItem := range items {
		// 站外转站内查询
		// 站外 to 站内内容标记 doc=0，且DocType不为空，且URL不等于空
		if contentItem.GetBizItem().GetItemMeta().DocId == 0 &&
			contentItem.GetBizItem().GetItemMeta().DocType != content.DocType_Unknown &&
			contentItem.GetBizItem().GetItemMeta().Url != "" {

			outsideUrls = append(outsideUrls, contentItem.GetBizItem().GetItemMeta().Url)
			outsideMap[contentItem.GetBizItem().GetItemMeta().Url] = contentItem
		}
	}

	// 查询站外内容
	outsideResultMap := c.contentProdRpc.BatchCurlContentByUrl(ctx, outsideUrls)
	var outsideResultRecord []string

	for k, v := range outsideMap {
		contentInfo, isOk := outsideResultMap[k]
		if !isOk {
			continue
		}
		outsideResultRecord = append(outsideResultRecord, fmt.Sprintf("url:%s, title:%s, content:%s", k, contentInfo.GetTitle(), contentInfo.GetContent()))

		resMap[*data_frame.NewUniqueId(v.GetCommonItem().Id())] = contentInfo
	}

	constant.DataInputNodeLog.Infof(logCtx, "%v", outsideUrls)
	constant.DataOutputNodeLog.Infof(logCtx, "%v", outsideResultRecord)

	return resMap, nil
}

func (c *OutsideContentProdMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res *rpc.CurlRespInfo) error {
	if res == nil {
		return nil
	}
	logger := log.WithFields(ctx, map[string]any{
		"func": "OutsideContentProdMetaFetcherLogic-itemMerge",
	})

	// 非法校验
	_, subType, _ := util.ParseLinkInfo(res.GetURL())
	if subType != content_core_thrift.ContentTypeQuestion {
		if res.GetContent() == "" {
			return nil
		}
	}

	// 站外链接命中站内知识
	docId, err := cast.ToInt64E(res.GetObjectInfo().GetOutID())
	if err != nil {
		logger.Errorf(ctx, "cast to int64 error: %v", err)
		return nil
	}
	contentType := res.GetObjectInfo().GetType()
	docType := model.GetDocType(contentType)
	body := res.GetContent()

	if docId != 0 && docType != content.DocType_Unknown {
		// 如果是问题 需要把当前数据转为回答
		if docType == content.DocType_Question && res.GetSubInfos() != nil && len(res.GetSubInfos()) > 0 {
			answerRes := res.GetSubInfos()[0]
			// 站外链接命中站内知识
			docId, err = cast.ToInt64E(answerRes.GetObjectInfo().GetOutID())
			if err != nil {
				logger.Errorf(ctx, "question2answer cast to int64 error: %v", err)
				return nil
			}
			contentType = answerRes.GetObjectInfo().GetType()
			docType = model.GetDocType(contentType)
			body = answerRes.GetContent()
			// 如果当前 question，则question的标题为 answer的标题
			item.GetBizItem().GetItemMeta().Title = res.GetTitle()
			//item.GetBizItem().GetItemMeta().ContentInfo = &base.ContentInfo{
			//	ExtInfo: &base.ContentExtInfo{
			//		ParentInfo: &base.ContentIdentity{
			//			ContentID: res.GetObjectInfo().GetOutID(),
			//		},
			//	},
			//}
		}
		item.GetBizItem().GetItemMeta().DocId = docId
		item.GetBizItem().GetItemMeta().DocType = docType
	} else {
		if res.GetTitle() != "" {
			item.GetBizItem().GetItemMeta().Title = res.GetTitle()
		}
		if res.GetContent() != "" {
			item.GetBizItem().GetItemMeta().Content = res.GetContent()
		}
	}

	// 清洗 content 里的 html
	//hasEquation := util.ContentHasEquation(body)
	//if !hasEquation {
	filteredBody, err := util.ContentFilterHtml(ctx, body)
	if err == nil {
		item.GetBizItem().GetItemMeta().Content = filteredBody
	}
	//}
	return nil
}
