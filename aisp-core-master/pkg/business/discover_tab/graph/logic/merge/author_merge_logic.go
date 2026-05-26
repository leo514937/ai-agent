package merge

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	macro2 "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
	"github.com/spf13/cast"
	"golang.org/x/exp/slices"
)

// AuthorMergeLogic 搜索创作者的agent排序
// @logicConfig: 0 | rank field
// @logicConfig: 1 | rank beta
// @logicOutput: 0 | 排序后的结果. []*data_frame.ItemData[entities.Item]
type AuthorMergeLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	bgeEmbeddingRerankerClient rpc.KlaraRpcClient
	klaraHttpClient            rpc.KlaraHttp
}

func NewAuthorMergeLogic(name string, config map[string]string) *AuthorMergeLogic {
	res := &AuthorMergeLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.MergeFunc = res.rerank
	res.bgeEmbeddingRerankerClient = impl.GetBgeEmbeddingClient("bge-reranker")
	res.klaraHttpClient = impl.NewKlaraHttpImpl(2 * time.Second)
	return res
}

func (a *AuthorMergeLogic) rerank(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	startTime := time.Now()
	items := lo.Flatten(itemLists)
	span, ctx, logCtx, cacheRespInterface := logic_context.InitLogicContext(ctx, requestCtx, a.GetName(), "rerank.AuthorMergeLogic")
	defer logic_context.DeferContext(span, a.GetName(), requestCtx, &items)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	if cacheRespInterface != nil {
		cacheResp, isTypeOk := cacheRespInterface.([]*data_frame.ItemData[entities.Item])
		if isTypeOk {
			return cacheResp, nil
		}
	}

	logInfoBeforeRank := a.getLogInfos(items)

	items, _ = a.rerank0(ctx, logCtx, requestCtx, items)

	logInfoAfterRank := a.getLogInfos(items)

	// 新
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".author_merge.inside_rerank.length", float64(len(items)))
	// 老
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".author_merge.inside_rerank.length", requestCtx.GetBizContext().Scenes()), float64(len(items)))

	log.StatsdRecall(ctx, "author_merge", "chunk_resp", len(items))
	a.saveTracing(logCtx, logInfoBeforeRank, logInfoAfterRank, startTime.UnixMilli(), requestCtx)

	requestCtx.DataMap().SetObjMap(logCtx, a.GetOutputName(0), items)
	return items, nil
}

func (a *AuthorMergeLogic) rerank0(ctx context.Context, logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {

	var respItems = make([]*data_frame.ItemData[entities.Item], 0)

	if len(items) == 0 {
		log.Warnf(ctx, "author items size is 0")
		return respItems, nil
	}

	rankBeta := cast.ToFloat64(requestCtx.GetBizContext().GetLogicConfig(a.GetName(), conf.AuthorSearchAgentRankBeta))
	limitSize := cast.ToInt(requestCtx.GetBizContext().GetLogicConfig(a.GetName(), conf.RecallMergeTopK))
	guarantee := requestCtx.GetBizContext().GetLogicConfig(a.GetName(), conf.RecallMergeGuarantee)
	threshold := cast.ToFloat32(requestCtx.GetBizContext().GetLogicConfig(a.GetName(), conf.RecallMergeScoreThreshold))
	batchSize := requestCtx.GetBizContext().GetSummaryRecallReRankBatchSize()
	memberId := requestCtx.GetBizContext().MemberId()
	intentionStr, _ := requestCtx.DataMap().GetString(logCtx, macro2.ZagKeyIntention)
	intention := macro.IntentionType(intentionStr)

	author2Similarity := make(map[int64]float64)
	author2Rank := make(map[int64]float64)
	author2Text := make(map[int64]string)
	author2Meta := make(map[int64]*model.AuthorUserMeta)

	authorUniqueMap := make(map[int64]*data_frame.ItemData[entities.Item])

	var uniqueItems []*data_frame.ItemData[entities.Item]
	// 一个创作者可能会召回多个，比如 数学话题优秀答主苏剑林 对应一条；互联网话题优秀答主苏剑林 也会有一条。一条只出现一次。
	for i, item := range items {
		authorId := item.GetBizItem().ItemMeta.AuthorId
		authorContent := item.GetBizItem().Text
		authorMeta := item.GetBizItem().ItemMeta.AuthorUserMeta

		if uniqueItem, exist := authorUniqueMap[authorId]; !exist {
			uniqueItems = append(uniqueItems, item)
		} else {
			uniqueItem.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources = conf.KbSourceSort(append(
				uniqueItem.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources,
				item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources...,
			))
		}

		author2Text[authorId] = authorContent
		author2Meta[authorId] = authorMeta
		author2Rank[authorId] = author2Rank[authorId] + 1.0/float64(len(items)+i)
	}

	queryMerge := requestCtx.GetBizContext().GetQueryMergeText()

	// 求 similar
	similarTexts := lo.Map(uniqueItems, func(item *data_frame.ItemData[entities.Item], _ int) string {
		return item.GetBizItem().GetItemMeta().Content
	})

	var similarScores = a.klaraHttpClient.BatchInferPairwiseScoreBySize(ctx, rpc.KlaraServiceUrlBgeRerank, rpc.KlaraRerankRequest{
		Query: queryMerge,
		Texts: similarTexts,
	}, batchSize)

	if len(similarScores) == len(uniqueItems) {
		for i, item := range uniqueItems {
			score := similarScores[i]
			if score >= threshold || item.GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource() == conf.KbSourceAuthorSelf {
				author2Similarity[item.GetBizItem().GetItemMeta().AuthorId] = float64(score)
				respItems = append(respItems, item)
			}
		}
	} else {
		log.Warnf(ctx, "scores len not equal to textParts len")
	}

	author2Similarity = a.similarityBoostByRank(author2Similarity, author2Rank)

	author2Score := a.calculateScore(author2Similarity, author2Meta, rankBeta)

	respItems = a.rankByScore(respItems, author2Score)

	respItems = a.limit(respItems, limitSize, guarantee)

	a.userOwnRemakeSource(respItems, memberId, intention)

	requestCtx.DataMap().SetObjMap(logCtx, a.GetOutputName(0), respItems)
	return respItems, nil
}

func (a *AuthorMergeLogic) getLogInfos(items []*data_frame.ItemData[entities.Item]) []string {
	info := lo.Map(items, func(item *data_frame.ItemData[entities.Item], _ int) string {
		return fmt.Sprintf("%d|%s", item.GetBizItem().ItemMeta.AuthorId,
			lo.Ternary(item.GetBizItem().ItemMeta.AuthorUserMeta != nil, item.GetBizItem().ItemMeta.AuthorUserMeta.AuthorName, ""))
	})

	return info
}

func (a *AuthorMergeLogic) similarityBoostByRank(similarity map[int64]float64, rank map[int64]float64) map[int64]float64 {
	author2Similarity := make(map[int64]float64)
	for authorId, sim := range similarity {
		author2Similarity[authorId] = sim * (1 + rank[authorId])
	}
	return author2Similarity
}

func (a *AuthorMergeLogic) calculateScore(author2Similarity map[int64]float64, author2Meta map[int64]*model.AuthorUserMeta, rankBeta float64) map[int64]float64 {
	author2Score := make(map[int64]float64)

	if len(author2Similarity) == 0 || len(author2Meta) == 0 {
		return author2Score
	}

	rankFiledMax := 0
	rankFiledMin := math.MaxInt64
	for _, meta := range author2Meta {
		rankFieldValue := meta.FollowerCnt
		if rankFieldValue > rankFiledMax {
			rankFiledMax = rankFieldValue
		}

		if rankFieldValue < rankFiledMin {
			rankFiledMin = rankFieldValue
		}
	}

	minSimilarity := slices.Min(lo.Values(author2Similarity))
	maxSimilarity := slices.Max(lo.Values(author2Similarity))

	for authorId, similarity := range author2Similarity {
		rankFieldValue := author2Meta[authorId].FollowerCnt

		rankFieldScore := float64(rankFieldValue-rankFiledMin) / util.CastZeroFloat(float64(rankFiledMax-rankFiledMin), 1)

		similarityScore := (similarity - minSimilarity) / util.CastZeroFloat(maxSimilarity-minSimilarity, 1)

		score := (1-rankBeta)*similarityScore + rankBeta*rankFieldScore
		score = (author2Meta[authorId].Boost/2 + 1.0) * score

		author2Score[authorId] = score
	}

	return author2Score
}

func (a *AuthorMergeLogic) rankByScore(items []*data_frame.ItemData[entities.Item], score map[int64]float64) []*data_frame.ItemData[entities.Item] {
	sort.Slice(items, func(i, j int) bool {
		authorIdI := items[i].GetBizItem().ItemMeta.AuthorId
		authorIdJ := items[j].GetBizItem().ItemMeta.AuthorId

		return score[authorIdI] > score[authorIdJ]
	})

	return items
}

func (a *AuthorMergeLogic) limit(items []*data_frame.ItemData[entities.Item], limit int, guaranteeBucket string) []*data_frame.ItemData[entities.Item] {
	var result []*data_frame.ItemData[entities.Item]

	guaranteeBucketMap := map[string]int{}
	for _, bucket := range strings.Split(guaranteeBucket, ",") {
		kv := strings.Split(bucket, ":")
		if len(kv) != 2 {
			break
		}
		guaranteeBucketMap[kv[0]] = cast.ToInt(kv[1])
	}

	for _, item := range items {
		sourceName := item.GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource().String()
		// 命中分桶保量队列的，单独计数存放
		if guaranteeBucketMap[sourceName] > 0 {
			result = append(result, item)
			guaranteeBucketMap[sourceName]--
		} else if limit > 0 {
			result = append(result, item)
			limit--
		}
	}

	return result
}

// 截取 topK 之后，如果通用创作者搜索搜到了自己，那么按照搜自己逻辑处理，添加 author_self 源
func (a *AuthorMergeLogic) userOwnRemakeSource(items []*data_frame.ItemData[entities.Item], memberId int64, intention macro.IntentionType) {
	if intention != macro.GetQueryRouteAuthor() {
		return
	}
	for _, item := range items {
		if item.GetBizItem().GetItemMeta().AuthorId == memberId && item.GetBizItem().ItemMeta.GetRecallSourceInfo().GetFirstKbSource() != conf.KbSourceAuthorSelf {
			item.GetBizItem().ItemMeta.GetRecallSourceInfo().KbSources = slices.Insert(item.GetBizItem().ItemMeta.GetRecallSourceInfo().KbSources, 0, conf.KbSourceAuthorSelf)
			break
		}
	}
}

func (a *AuthorMergeLogic) saveTracing(logCtx context.Context, request []string, response []string, startTime int64, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
	logicTracing := &proto.LogicTracing{
		LogicName:   a.GetName(),
		LogicInput:  request,
		LogicOutput: response,
		EdgeSelect:  "",
		StartTimeMs: startTime,
		EndTimeMs:   time.Now().UnixMilli(),
		CostMs:      time.Now().UnixMilli() - startTime,
	}
	requestCtx.GetBizContext().AddLogicTracing(a.GetName(), logicTracing)

	constant.DataInputNodeLog.Infof(logCtx, "%v", request)
	constant.DataOutputNodeLog.Infof(logCtx, "%v", response)
}
