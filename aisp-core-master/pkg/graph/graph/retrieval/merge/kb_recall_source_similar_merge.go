package merge

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	util3 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"

	//"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

// @logicAuthor: wangran
// @logicInfo: 召回队列合并去重，卡相似度阈值
// @logicOutput: 0 | 召回结果。[]*data_frame.ItemData[entities.Item]

type KbRecallSourceSimilarLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	klaraHttpClient rpc.KlaraHttp
}

func NewKbRecallSourceSimilarLogic(name string, config map[string]string) *KbRecallSourceSimilarLogic {
	res := &KbRecallSourceSimilarLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.realMerge
	res.klaraHttpClient = impl.NewKlaraHttpImpl(2 * time.Second)
	return res
}

type BatchScore struct {
	batchIndex int
	scores     []float32
}

func (k *KbRecallSourceSimilarLogic) realMerge(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	var respItems = make([]*data_frame.ItemData[entities.Item], 0)

	span, ctx, logCtx, cacheRespInterface := logic_context.InitLogicContext(ctx, requestCtx, k.GetName(), "recall.KbRecallSourceMergeLogic.realMerge")
	defer logic_context.DeferContext(span, k.GetName(), requestCtx, &respItems)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	startTime := time.Now().UnixMilli()

	if cacheRespInterface != nil {
		cacheResp, isTypeOk := cacheRespInterface.([]*data_frame.ItemData[entities.Item])
		if isTypeOk {
			return cacheResp, nil
		}
	}

	topK := cast.ToInt(requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallMergeTopK))
	threshold := cast.ToFloat32(requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallMergeScoreThreshold))
	sourceThresholdStr := requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallMergeScoreSourceThreshold)
	textField := requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallMergeScoreTextField)
	textFieldStr := requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallMergeScoreTextSourceField)
	priorityTagCoreKVStr := requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallMergePriorityTagCoreKV)
	batchSize := requestCtx.GetBizContext().GetSummaryRecallReRankBatchSize()
	queryMerge := requestCtx.GetBizContext().GetQueryMergeText()
	var similarModel rpc.KlaraServiceUrl
	if modelStr := requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallMergeModel); modelStr != "" {
		similarModel = rpc.KlaraServiceUrl(modelStr)
	} else {
		similarModel = rpc.KlaraServiceUrlBgeRerank
	}

	// 支持 merge 时根据不同召回源，给定不同的 field
	textFieldMap := map[conf.KbSource]enums.SimilarTextType{}
	for _, textFieldItem := range strings.Split(textFieldStr, ";") {
		textFieldSlice := strings.Split(textFieldItem, ":")
		if len(textFieldSlice) != 2 {
			continue
		}
		textFieldMap[conf.KbSource(textFieldSlice[0])] = enums.SimilarTextType(textFieldSlice[1])
	}

	// 支持 merge 时根据不同召回源，给定不同的 threshold
	sourceThresholdMap := map[conf.KbSource]float32{}
	for _, sourceThresholdItem := range strings.Split(sourceThresholdStr, ";") {
		sourceThresholdSlice := strings.Split(sourceThresholdItem, ":")
		if len(sourceThresholdSlice) != 2 {
			continue
		}
		sourceThresholdMap[conf.KbSource(sourceThresholdSlice[0])] = cast.ToFloat32(sourceThresholdSlice[1])
	}

	itemList := lo.Flatten(itemLists)

	if topK == 0 {
		return itemList, nil
	}

	// 去重，除了通用的去重外，还需要进行标题和摘要去重
	uniqueTitleAbstract := map[string]bool{}
	firstRemoveDupSlice := entities.ItemListMergeDuplicate(itemList)
	var removedDupSlice []*data_frame.ItemData[entities.Item]
	for _, item := range firstRemoveDupSlice {
		// 站内内容不需要进行二次去重
		if !item.GetBizItem().GetItemMeta().IsOutLink() {
			removedDupSlice = append(removedDupSlice, item)
			continue
		}
		// 现针对标题和摘要做去重，避免两个不同的 url 实际上对应着同样的内容。去重方式当前硬匹配，后续可以相似度匹配
		uniqueKey := fmt.Sprintf("%s#%s", item.GetBizItem().GetItemMeta().Title, item.GetBizItem().GetItemMeta().Abstract)
		if uniqueTitleAbstract[uniqueKey] {
			continue
		}
		uniqueTitleAbstract[uniqueKey] = true
		removedDupSlice = append(removedDupSlice, item)
	}

	// 求 similar
	similarTexts := lo.Map(removedDupSlice, func(item *data_frame.ItemData[entities.Item], index int) string {
		similarTextType := enums.SimilarTextType(textField)
		if similarTextTypeByMap, exist := textFieldMap[item.GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource()]; exist {
			similarTextType = similarTextTypeByMap
		}
		return k.getSimilarText(similarTextType, item.GetBizItem().GetItemMeta())
	})

	// 开并发处理 BatchInferPairwiseScoreBySize
	similarScores := make([]float32, len(similarTexts))
	if len(similarTexts) > 0 {
		// 创建并发组
		group := safe_group.NewGroupWithTimeout("KbRecallSourceSimilarLogic", 10000).SetLimit(10)

		// 将 similarTexts 分批
		textBatches := lo.Chunk(similarTexts, batchSize)

		// 创建结果通道
		resultChan := make(chan BatchScore, len(textBatches))

		// 并发处理每个批次
		for batchIndex, textBatch := range textBatches {
			group.Go(func() error {
				defer func() {
					if r := recover(); r != nil {
						log.Warnf(ctx, "KbRecallSourceSimilarLogic Panic => %v", r)
					}
				}()

				// 调用 BatchInferPairwiseScoreBySize
				batchScores := k.klaraHttpClient.BatchInferPairwiseScoreBySize(ctx, similarModel, rpc.KlaraRerankRequest{
					Query: queryMerge,
					Texts: textBatch,
				}, batchSize)

				// 发送结果到通道
				resultChan <- BatchScore{
					batchIndex: batchIndex,
					scores:     batchScores,
				}

				return nil
			})
		}

		// 等待所有 goroutine 完成并关闭通道
		go func() {
			wgErr := group.Wait()
			if wgErr != nil {
				log.Errorf(ctx, "KbRecallSourceSimilarLogic Wait Err => %v", wgErr)
			}
			close(resultChan)
		}()

		// 收集结果
		for result := range resultChan {
			startIndex := result.batchIndex * batchSize
			endIndex := startIndex + len(result.scores)
			if endIndex > len(similarScores) {
				endIndex = len(similarScores)
			}
			copy(similarScores[startIndex:endIndex], result.scores)
		}
	}

	if len(similarScores) == len(removedDupSlice) {
		for i, item := range removedDupSlice {
			score := similarScores[i]
			scoreThreshold := threshold
			if sourceThreshold, exist := sourceThresholdMap[item.GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource()]; exist {
				scoreThreshold = sourceThreshold
			}
			if score >= scoreThreshold {
				// 为了区分后面 rerank 阶段的 similar score，这里作为全局视角的召回环节使用 recall score
				item.GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallScore = float64(similarScores[i])
				respItems = append(respItems, item)
			}
		}
	} else {
		log.Warnf(ctx, "scores len not equal to textParts len")
	}

	rankMethod := conf.SortMethod(util2.SafeString2Int64(requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallMergeSortMethodField), 0))
	switch rankMethod {
	case conf.SortMethodSimilarScore:
		// similar 降序排序
		sort.Slice(respItems, func(i, j int) bool {
			return respItems[i].GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallScore > respItems[j].GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallScore
		})
	case conf.SortMethodSourceOrder:
		// 按照 sourceOrder 排序
		recallSourceOrder := requestCtx.GetBizContext().GetLogicConfig(k.GetName(), conf.RecallMergeSourceOrderField)
		if recallSourceOrder != "" {
			recallSourceOrderList := strings.Split(recallSourceOrder, ",")
			// 将respItems按照recallSourceOrderList的顺序排序，如果recallSourceOrderList中没有的source，放在最后
			sort.Slice(respItems, func(i, j int) bool {
				iSource := respItems[i].GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource().String()
				jSource := respItems[j].GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource().String()
				iIndex := lo.IndexOf(recallSourceOrderList, iSource)
				jIndex := lo.IndexOf(recallSourceOrderList, jSource)
				if iIndex < 0 {
					iIndex = len(recallSourceOrderList)
				}
				if jIndex < 0 {
					jIndex = len(recallSourceOrderList)
				}
				return iIndex < jIndex
			})
		}
	}

	if priorityTagCoreKVStr != "" {
		respItems = k.handlePriority(priorityTagCoreKVStr, respItems)
	}

	constant.DataOutputNodeLog.Infof(logCtx, "outputSize:%s, similarScores:%s", len(respItems), util.GetJSONIgnoreError(similarScores))
	result := respItems[0:util.Min(topK, len(respItems))]
	k.saveTracing(itemList, result, similarScores, startTime, requestCtx)
	return result, nil
}

// 排序保量逻辑
func (k *KbRecallSourceSimilarLogic) handlePriority(priorityTagCoreKVStr string, respItems []*data_frame.ItemData[entities.Item]) []*data_frame.ItemData[entities.Item] {
	priorityTagCoreKVMap := make(map[string]string)
	if priorityTagCoreKVStr != "" {
		priorityTagCoreKVList := strings.Split(priorityTagCoreKVStr, ",")
		for _, priorityTagCoreKV := range priorityTagCoreKVList {
			priorityTagCoreKVSlice := strings.Split(priorityTagCoreKV, ":")
			if len(priorityTagCoreKVSlice) != 2 {
				continue
			}
			priorityTagCoreKVMap[priorityTagCoreKVSlice[0]] = priorityTagCoreKVSlice[1]
		}
	}

	var priorityItems []*data_frame.ItemData[entities.Item]
	var otherItems []*data_frame.ItemData[entities.Item]

	for _, item := range respItems {
		isPriority := false
		for tagKey, tagValue := range priorityTagCoreKVMap {
			if util3.GetTagValueString(item.GetBizItem().GetItemMeta().TagInfo, tagKey) == tagValue {
				isPriority = true
				break
			}
		}
		if isPriority {
			priorityItems = append(priorityItems, item)
		} else {
			otherItems = append(otherItems, item)
		}
	}

	return append(priorityItems, otherItems...)
}

func (k *KbRecallSourceSimilarLogic) saveTracing(input []*data_frame.ItemData[entities.Item], output []*data_frame.ItemData[entities.Item], similarScores []float32, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicInput := lo.Map(input, func(item *data_frame.ItemData[entities.Item], _ int) string {
		return item.GetBizItem().ToDescription()
	})
	logicOutput := lo.Map(output, func(item *data_frame.ItemData[entities.Item], _ int) string {
		return item.GetBizItem().ToDescription()
	})

	logicTracing := &proto.LogicTracing{
		LogicName:    k.GetName(),
		LogicInput:   logicInput,
		LogicOutput:  logicOutput,
		LogicProcess: util.GetJSONIgnoreError(similarScores),
		EdgeSelect:   "",
		StartTimeMs:  startTime,
		EndTimeMs:    time.Now().UnixMilli(),
		CostMs:       time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(k.GetName(), logicTracing)
}

func (k *KbRecallSourceSimilarLogic) getSimilarText(textField enums.SimilarTextType, itemMeta *model.ItemMeta) string {
	switch textField {
	case enums.SimilarTextTypeByTitle:
		return itemMeta.Title
	case enums.SimilarTextTypeByTitleAndContent2048:
		return fmt.Sprintf("%s\n%s", itemMeta.Title, util2.UnicodeSubstr(itemMeta.Content, 0, 2048))
	case enums.SimilarTextTypeByTitleAndAbstract:
		return fmt.Sprintf("%s\n%s", itemMeta.Title, itemMeta.Abstract)
	case enums.SimilarTextTypeByContent2048:
		return util2.UnicodeSubstr(itemMeta.Content, 0, 2048)
	default:
		return ""
	}
}
