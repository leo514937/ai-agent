package meta_fetcher

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/fetch"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

type ChildContentCoreMetaFetcherLogic struct {
	*fetch.FetcherLogic[entities.RequestContext, entities.User, entities.Item, []*base.ContentInfo]
	contentCoreRpc rpc.ContentCoreRPC
	metis2Rpc      rpc.Metis2Rpc
}

func NewChildContentCoreMetaFetcherLogic(name string, config map[string]string) *ChildContentCoreMetaFetcherLogic {
	res := &ChildContentCoreMetaFetcherLogic{
		FetcherLogic: fetch.NewFetcherLogic[entities.RequestContext, entities.User, entities.Item, []*base.ContentInfo](name, config),
	}
	res.FetchFunc = res.fetch
	res.ItemMergeFunc = res.itemMerge
	res.contentCoreRpc = impl.DefaultContentCoreRPCImpl
	res.metis2Rpc = impl.DefaultMetis2RPCImpl
	return res
}

func (c *ChildContentCoreMetaFetcherLogic) fetch(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) (map[data_frame.UniqueId][]*base.ContentInfo, error) {
	resMap := make(map[data_frame.UniqueId][]*base.ContentInfo)

	if items == nil || len(items) == 0 {
		return resMap, nil
	}

	questionItems := lo.Filter(items, func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().GetItemMeta().DocType == content.DocType_Question
	})

	// 从 question 到 questionId
	var questionIds []int64
	var questionIdMap = make(map[data_frame.UniqueId]int64)
	for _, questionItem := range questionItems {
		questionId := questionItem.GetBizItem().GetItemMeta().DocId
		questionIds = append(questionIds, questionId)
		questionIdMap[*data_frame.NewUniqueId(questionItem.GetCommonItem().Id())] = questionId
	}

	if len(questionIds) == 0 {
		return resMap, nil
	}

	// 从 questionId 到 answerId
	questionAnswerIdMap := c.metis2Rpc.ConcurrentGetQuestionAnswerIds(ctx, questionIds, 1, 10)
	var answers []model.Content
	for _, answerIds := range questionAnswerIdMap {
		for _, answerId := range answerIds {
			answers = append(answers, model.Content{
				ContentID:   answerId,
				ContentType: content.DocType_Answer,
			})
		}
	}

	// 从 answerId 到 answerContentInfo
	answerContentInfo := c.contentCoreRpc.BatchGetContent(ctx, answers,
		base.ContentInfoFieldContentTitle,
		base.ContentInfoFieldContentDetail,
		base.ContentInfoFieldContentBody)

	//	拼装结果
	for uniqueKey, questionId := range questionIdMap {
		answerIds := questionAnswerIdMap[questionId]
		var answerContentInfos []*base.ContentInfo
		for _, answerId := range answerIds {
			answerContent := model.Content{
				ContentID:   answerId,
				ContentType: content.DocType_Answer,
			}
			if answerContentInfo[answerContent] != nil {
				answerContentInfos = append(answerContentInfos, answerContentInfo[answerContent])
			}
		}
		resMap[uniqueKey] = answerContentInfos
	}
	return resMap, nil
}

func (c *ChildContentCoreMetaFetcherLogic) itemMerge(ctx context.Context, item *data_frame.ItemData[entities.Item], res []*base.ContentInfo) error {
	if res == nil {
		return nil
	}

	item.GetBizItem().GetItemMeta().ChildContentInfo = res
	return nil
}
