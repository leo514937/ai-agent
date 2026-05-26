package rerank

import (
	"context"
	"fmt"
	"sort"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/logic_context"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/similar"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/constant"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"github.com/samber/lo"
	"github.com/spf13/cast"
	"golang.org/x/net/html"
	"golang.org/x/net/html/atom"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 召回内容分块重排序

type KbRecallChunkAndReRankLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
	similarService    service.SimilarService
	contentBodyMinLen int
	contentBodyMaxLen int
	chunkSize         int
	chunkMaxSize      int
	chunkOverlap      int
}

func NewKbRecallChunkAndReRankLogic(name string, config map[string]string) *KbRecallChunkAndReRankLogic {
	res := &KbRecallChunkAndReRankLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.similarService = service.NewSimilarService("ensemble")
	res.contentBodyMinLen = 10
	res.contentBodyMaxLen = 10240
	res.chunkSize = 512
	res.chunkMaxSize = 800
	res.chunkOverlap = 100
	res.MappingFunc = res.realChunkAndReRank
	return res
}

func (s *KbRecallChunkAndReRankLogic) realChunkAndReRank(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	// 如果为ZHIDA_TAB，直接返回
	if requestCtx.GetBizContext().GetBizType() == proto.ChatType_ZHIDA_TAB.String() {
		return items, nil
	}

	resp := make([]*data_frame.ItemData[entities.Item], 0)
	span, ctx, logCtx, cacheRespInterface := logic_context.InitLogicContext(ctx, requestCtx, s.GetName(), "recall.KbRecallChunkAndReRankLogic.realChunkAndReRank")
	defer logic_context.DeferContext(span, s.GetName(), requestCtx, &resp)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItems(items))

	if cacheRespInterface != nil {
		cacheResp, isTypeOk := cacheRespInterface.([]*data_frame.ItemData[entities.Item])
		if isTypeOk {
			return cacheResp, nil
		}
	}

	// 相关性阈值
	var similarThreshold float64 = 0
	if similarThresholdStr := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.SummaryConfigLogicByThreshold.ToConvert()); similarThresholdStr != "" {
		similarThreshold = cast.ToFloat64(similarThresholdStr)
	}

	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallChunkAndReRankLogic realChunkAndReRank",
	})
	logger.Debugf(ctx, "do running")

	log.StatsdRecall(ctx, "chunk", "chunk_start", len(items))

	query := requestCtx.GetBizContext().GetQueryMergeText()
	if query == "" {
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	if items == nil || len(items) == 0 {
		logger.Warn(ctx, "contents is nil or len(contents) == 0")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 打点 用于记录召回站外内容占知乎内容 独占比
	retrieval.SaveRecallZhihuMonopolyRatioStatsd(ctx, items, "before")

	// 内容切块和打分
	contents := s.contentChunkAndScore(ctx, requestCtx, query, items)
	log.StatsdRecall(ctx, "chunk", "chunk_content", len(contents))
	// 内容重排序
	relContent := s.contentReRank(ctx, contents, similarThreshold)
	log.StatsdRecall(ctx, "chunk", "chunk_rerank", len(relContent))
	if len(relContent) == 0 {
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	respRecord := make([]string, 0)
	for _, contentItem := range relContent {
		item := contentItem.Item
		item.GetBizItem().Text = contentItem.Text
		item.GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallScore = contentItem.Score
		item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used = true
		respRecord = append(respRecord, fmt.Sprintf("text:%s, score:%f", contentItem.Text, contentItem.Score))
		resp = append(resp, item)
	}

	constant.DataOutputNodeLog.Infof(logCtx, "%v", respRecord)
	// 新
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".rerank.inside_rerank.length", float64(len(resp)))
	// 老
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank.inside_rerank.length", requestCtx.GetBizContext().Scenes()), float64(len(resp)))

	log.StatsdRecall(ctx, "chunk", "chunk_resp", len(resp))
	return resp, nil
}

// contentChunkAndScore 内容切块并评分
func (s *KbRecallChunkAndReRankLogic) contentChunkAndScore(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	query string, items []*data_frame.ItemData[entities.Item]) []*retrieval.RecallTextAndScore {

	span, ctx, _ := log.StartChildSpanWithContext(ctx, "recall.KbRecallChunkAndReRankLogic.contentChunkAndScore")
	defer span.Finish()

	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallChunkAndReRankLogic contentChunkAndScore",
	})

	var chunksText []string
	var textParts []*retrieval.RecallTextAndScore
	for _, item := range items {
		body := util.HTMLFilter(item.GetBizItem().GetItemMeta().Content, func(node *html.Node) bool {
			if node == nil {
				return false
			}
			return node.DataAtom != atom.A && node.DataAtom != atom.Sup
		})
		body, _ = util.ToPlainText(body)
		if util.UnicodeLen(body) < s.contentBodyMinLen {
			logger.Warnf(ctx, "contentBody length  < %d, so continue", s.contentBodyMinLen)
			continue
		}

		if util.UnicodeLen(body) > s.contentBodyMaxLen {
			body = util.UnicodeSubstr(body, 0, s.contentBodyMaxLen)
		}

		texts := util.SplitText([]rune(body), s.chunkSize, s.chunkMaxSize, s.chunkOverlap)
		// 2024年02月21日15:53:19 过滤 chunkOverlap 可能会影响召回内容结果 经过讨论 删除该处理
		//texts = lo.Filter(texts, func(text string, _ int) bool {
		//	return util.UnicodeLen(text) >= s.chunkOverlap
		//})
		textParts = append(textParts, lo.Map(texts, func(text string, _ int) *retrieval.RecallTextAndScore {
			chunksText = append(chunksText, text)
			return &retrieval.RecallTextAndScore{Text: text, Item: item}
		})...)
	}

	batchSize := requestCtx.GetBizContext().GetSummaryRecallEmbeddingBatchSize()
	// 求 similar
	scores := s.similarService.BatchGetSimilarScoreBySize(ctx, query, chunksText, batchSize)
	if len(scores) == len(textParts) {
		for i := range textParts {
			textParts[i].Score = scores[i]
		}
	} else {
		logger.Warnf(ctx, "scores len not equal to textParts len")
	}
	return textParts
}

// contentReRank 排序后去除指定个数
func (s *KbRecallChunkAndReRankLogic) contentReRank(ctx context.Context, chunks []*retrieval.RecallTextAndScore, similarThreshold float64) []*retrieval.RecallTextAndScore {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "recall.KbRecallChunkAndReRankLogic.contentReRank")
	defer span.Finish()

	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallChunkAndReRankLogic contentReRank",
	})
	if chunks == nil || len(chunks) == 0 {
		logger.Warn(ctx, "chunks is nil or len(chunks) == 0")
		return []*retrieval.RecallTextAndScore{}
	}

	// 按照相关性阈值进行过滤
	filtersPart := lo.Filter(chunks, func(item *retrieval.RecallTextAndScore, _ int) bool {
		return item.Score >= similarThreshold
	})
	if filtersPart == nil || len(filtersPart) == 0 {
		logger.Warn(ctx, "filtersPart chunks is nil or len(chunks) == 0")
		return []*retrieval.RecallTextAndScore{}
	}

	// Score 倒序排序
	sort.Slice(filtersPart, func(i, j int) bool {
		return filtersPart[i].Score > filtersPart[j].Score
	})

	// 去重处理优先保留分高的 item
	docSet := make(map[int64]struct{})
	var finalPart []*retrieval.RecallTextAndScore
	for _, each := range filtersPart {
		if _, ok := docSet[(*each).Item.GetBizItem().GetItemMeta().DocId]; !ok {
			finalPart = append(finalPart, each)
			docSet[(*each).Item.GetBizItem().GetItemMeta().DocId] = struct{}{}
		}
	}

	return finalPart
}
