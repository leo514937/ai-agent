package rerank

import (
	"context"
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strconv"
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
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/rerank/rerank_util"
	graphUtil "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 召回内容分块打分v2

type itemChunkerMeta struct {
	item           *data_frame.ItemData[entities.Item]
	textId         int
	chunkMetaRes   *rerank_util.ChunkMetaRes
	chunkRes       *rerank_util.ChunkRes
	finalScore     float64
	active         bool
	keyContentDict map[int]string
}

type KbRecallChunkAndScoreLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	klaraHttpClient rpc.KlaraHttp
	defScale        float64
	reRankLimit     int
	reRankTimeout   int64
}

func NewKbRecallChunkAndScoreLogic(name string, config map[string]string) *KbRecallChunkAndScoreLogic {
	res := &KbRecallChunkAndScoreLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.reRankLimit = 500
	res.reRankTimeout = 10000
	// 默认加权 指数
	res.defScale = 1
	res.klaraHttpClient = impl.NewKlaraHttpImpl(2 * time.Second)
	res.MergeFunc = res.realChunkAndReRank
	return res
}

func (s *KbRecallChunkAndScoreLogic) getLogicConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) (conf.RecallChunkReRankConfig, bool) {
	logicConfigStr := requestCtx.GetBizContext().GetLogicConfig(s.GetName(), conf.JsonConfigLogicKey.ToConvert())
	if logicConfigStr == "" {
		log.Errorf(ctx, "KbRecallChunkAndScoreLogic getConfig error => config is empty")
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_empty.%s.count", requestCtx.GetBizContext().Scenes(), s.GetName()))
		return conf.RecallChunkReRankConfig{}, false
	}
	recallChunkReRankConfig := conf.RecallChunkReRankConfig{}
	err := json.Unmarshal([]byte(logicConfigStr), &recallChunkReRankConfig)
	if err != nil {
		log.Errorf(ctx, "KbRecallChunkAndScoreLogic getConfig error => %s", err)
		statsd.Increment(fmt.Sprintf(macro.CommonErrorStatsPrefix+".config_unmarshal.%s.count", requestCtx.GetBizContext().Scenes(), s.GetName()))
		return conf.RecallChunkReRankConfig{}, false
	}
	return recallChunkReRankConfig, true
}

func (s *KbRecallChunkAndScoreLogic) realChunkAndReRank(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	resp := make([]*data_frame.ItemData[entities.Item], 0)
	span, ctx, _, cacheRespInterface := logic_context.InitLogicContext(ctx, requestCtx, s.GetName(), "recall.KbRecallChunkAndScoreLogic.realChunkAndReRank")
	defer logic_context.DeferContext(span, s.GetName(), requestCtx, &resp)
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))
	logger := log.WithFields(ctx, map[string]any{
		"func": "KbRecallChunkAndScoreLogic realChunkAndReRank",
	})
	logger.Debugf(ctx, "do running")
	if cacheRespInterface != nil {
		cacheResp, isTypeOk := cacheRespInterface.([]*data_frame.ItemData[entities.Item])
		if isTypeOk {
			return cacheResp, nil
		}
	}

	// 过滤chunk
	items := lo.Filter(lo.Flatten(itemLists), func(item *data_frame.ItemData[entities.Item], index int) bool {
		return item.GetBizItem().ChatTextTurnoverType == entities.ChatMappingTypeRecallChunk
	})

	if items == nil || len(items) == 0 {
		logger.Warn(ctx, "contents is nil or len(contents) == 0")
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	chunkReRankConfig, isConfigOk := s.getLogicConfig(ctx, requestCtx)
	if !isConfigOk {
		return []*data_frame.ItemData[entities.Item]{}, nil
	}

	// 如果设置为直接跳过 则直接返回（新版）
	// 如果 item len 为1，且当前为 any模式，且当前item长度不超过 1w 则为单篇模式，否则都要进行切chunk打分排序
	if chunkReRankConfig.IsAllowItemSkipChunk || (chunkReRankConfig.IsAllowSingleItemSkipChunk && len(items) == 1) {
		contentLength := 0
		for _, item := range items {
			item.GetBizItem().Text = item.GetBizItem().GetItemMeta().Content
			item.GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallScore = 1
			item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used = true
			item.GetBizItem().ChatTextTurnoverType = entities.ChatMappingTypeRecallChunk
			contentLength += util.UnicodeLen(item.GetBizItem().Text)
			resp = append(resp, item)
		}
		// 打点 & 记录 tracing
		// 召回源数量
		statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank_v2.length", requestCtx.GetBizContext().Scenes()), float64(len(resp)))
		// 切chunk数量
		statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank_v2.chunk_length", requestCtx.GetBizContext().Scenes()), float64(len(resp)))
		// 有效的chunk数量
		statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank_v2.used_length", requestCtx.GetBizContext().Scenes()), float64(len(resp)))
		// 有效的chunk unicode 长度
		statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank_v2.used_content_unicode_length", requestCtx.GetBizContext().Scenes()), float64(contentLength))
		return resp, nil
	}

	query := requestCtx.GetBizContext().GetQueryMergeText()

	if chunkReRankConfig.ModelName == "" {
		chunkReRankConfig.ModelName = string(rpc.KlaraServiceUrlBgeRerank)
	}

	// 需要再上游做好，rerank算子不再关心去重问题，业务解耦
	// 针对 每个item，单独创建 chunker
	itemMap := make(map[int]*itemChunkerMeta)
	itemChunkerMap := make(map[int]*rerank_util.DocumentChunker)
	for itemIndex, item := range items {
		var text *string
		text = lo.ToPtr(item.GetBizItem().GetItemMeta().Content)
		if chunkReRankConfig.UseRaw && item.GetBizItem().GetItemMeta().Raw != "" {
			text = lo.ToPtr(item.GetBizItem().GetItemMeta().Raw)
		}
		chunker := rerank_util.NewDocumentChunker(
			ctx,
			text,
			itemIndex,
			chunkReRankConfig.KeySize,
			chunkReRankConfig.KeyStep,
			chunkReRankConfig.ValueSize,
			chunkReRankConfig.KeyOffset,
			chunkReRankConfig.BoundaryRegex,
		)
		if chunker == nil {
			continue
		}

		itemChunkerMap[itemIndex] = chunker

		// 获取 chunks
		chunks := itemChunkerMap[itemIndex].Keys()
		keyContentDict := make(map[int]string)
		for _, chunk := range chunks {
			keyContentDict[chunk.ChunkId] = chunk.ChunkKeyText
		}

		itemMap[itemIndex] = &itemChunkerMeta{
			item:           item,
			textId:         itemIndex,
			keyContentDict: keyContentDict,
		}
	}

	// 并发处理多个召回内容的chunk（不确定是否有多线程问题 保险起见 将结果返回到 chan中）
	batchSize := requestCtx.GetBizContext().GetSummaryRecallReRankBatchSize()
	group := safe_group.NewGroupWithTimeout("KbRecallChunkAndScoreLogic", s.reRankTimeout).SetLimit(s.reRankLimit)
	chunkMetaResArr := make([]*rerank_util.ChunkMetaRes, 0)
	for textId := range itemMap {
		// 为了降低并发量，减少在服务端排队压力，这里需要再客户端进行排队
		// 先 生成 chunk 的 meta 信息
		chunksMetaRes := itemChunkerMap[textId].GetChunksMeta(query, func(ctx context.Context, query string, chunksText []string) []float32 {
			return make([]float32, len(chunksText))
		})
		chunkMetaResArr = append(chunkMetaResArr, chunksMetaRes...)
	}

	var chunkResultChan = make(chan *itemChunkerMeta, len(chunkMetaResArr))
	chunkMetaResBatchArr := lo.Chunk(chunkMetaResArr, batchSize)
	for _, chunkMetaResBatch := range chunkMetaResBatchArr {
		chunkMetaResBatch := chunkMetaResBatch
		group.Go(func() error {
			defer func() {
				if r := recover(); r != nil {
					logger.Warnf(ctx, "Chunker Panic => %v", r)
				}
			}()

			chunkTextArr := make([]string, 0)
			for _, chunkMetaRes := range chunkMetaResBatch {
				itemMeta := itemMap[chunkMetaRes.TextId]
				if itemMeta == nil {
					continue
				}

				chunkText, isOk := itemMeta.keyContentDict[chunkMetaRes.ChunkId]
				if !isOk {
					continue
				}

				chunkTextArr = append(chunkTextArr, chunkText)
			}

			var scoreBySize []float32
			if query == "" {
				scoreBySize = make([]float32, len(chunkTextArr))
			} else {
				scoreBySize = s.klaraHttpClient.BatchInferPairwiseScoreBySize(ctx, rpc.KlaraServiceUrl(chunkReRankConfig.ModelName), rpc.KlaraRerankRequest{
					Query: query,
					Texts: chunkTextArr,
				}, batchSize)
			}

			if len(scoreBySize) == batchSize {
				for i, chunkMetaRes := range chunkMetaResBatch {
					itemMeta := itemMap[chunkMetaRes.TextId]
					score := s.handleScoreScale(itemMeta.item, scoreBySize[i], chunkReRankConfig.ScoreScaleByTag)
					// 手动回填 score
					itemMeta.chunkMetaRes = itemChunkerMap[chunkMetaRes.TextId].SetChunkScore(chunkMetaRes.ChunkId, score)
					// 按照 chunk 裂变的结果
					chunkResultChan <- &itemChunkerMeta{
						item:           itemMeta.item,
						textId:         itemMeta.textId,
						chunkRes:       itemMeta.chunkRes,
						finalScore:     itemMeta.finalScore,
						active:         itemMeta.active,
						keyContentDict: itemMeta.keyContentDict,
						chunkMetaRes:   itemMeta.chunkMetaRes,
					}
				}
			}
			return nil
		})
	}

	// 等待所有 goroutine 完成
	go func() {
		wgErr := group.Wait()
		if wgErr != nil {
			logger.Errorf(ctx, "Chunker Wait Err => %v", wgErr)
		}
		close(chunkResultChan)
	}()

	// 遍历 chunk 按照 并加权排序
	chunkResultArr := make([]*itemChunkerMeta, 0)
	for chunkResult := range chunkResultChan {
		item := chunkResult.item
		scale, isExistScale := chunkReRankConfig.ScoreScales[item.GetBizItem().GetItemMeta().GetRecallSourceInfo().GetFirstKbSource()]
		if !isExistScale {
			scale = s.defScale
		}
		chunkResult.finalScore = math.Pow(float64(chunkResult.chunkMetaRes.Score), scale)
		chunkResultArr = append(chunkResultArr, chunkResult)
	}

	sort.Slice(chunkResultArr, func(i, j int) bool {
		return chunkResultArr[i].finalScore > chunkResultArr[j].finalScore
	})

	// 再次调整 chunkResultArr 的顺序
	chunkResultArr = rerankByQueryMerge(chunkResultArr)

	finalScores := lo.Map(chunkResultArr, func(item *itemChunkerMeta, _ int) float64 {
		return item.finalScore
	})
	scoreUsedIdxes := curve(finalScores, chunkReRankConfig.ScoreThreshold)

	// 用户 重新生成要求指定的召回源ID
	recallContentIds := requestCtx.GetBizContext().GetRecallContentIds()

	// 预处理数据 用于判断是否确定要走缓存策略（极限情况是上游recall 召回新内容，而这里确指定了旧id，这种情况下旧id不会限制chunk切块）
	itemRecallContentIds := make([]string, 0)
	for _, chunkResult := range chunkResultArr {
		itemRecallContentIds = append(itemRecallContentIds, chunkResult.item.GetBizItem().GetItemRecallContentId())
	}
	isUseCache := len(lo.Intersect(recallContentIds, itemRecallContentIds)) > 0

	// 处理保量策略
	guaranteedLength := 0
	guaranteedExistMap := make(map[string]bool)
	for _, chunkResult := range chunkResultArr {
		// 如果指定了召回源ID，且当前item 不在指定召回源内 则不做处理
		if isUseCache && len(recallContentIds) > 0 && !lo.Contains(recallContentIds, chunkResult.item.GetBizItem().GetItemRecallContentId()) {
			continue
		}
		guaranteedKey := getGuaranteedKey(requestCtx, chunkResult.item)
		// 如果有保量，每种保量策略只保 1 条 chunk
		if guaranteedKey == "" || guaranteedExistMap[guaranteedKey] {
			continue
		}
		// 判断保量内容加入后是否超出模型最大输入长度，超出则直接结束
		deltaLength := itemChunkerMap[chunkResult.textId].GetUseChunkLengthByDelta(chunkResult.chunkMetaRes.ChunkId)
		if guaranteedLength+deltaLength > chunkReRankConfig.TotalSize {
			break
		}
		// 标记保量内容
		itemChunkerMap[chunkResult.textId].MarkActive()
		itemChunkerMap[chunkResult.textId].UseChunk(chunkResult.chunkMetaRes.ChunkId)

		guaranteedLength += deltaLength
		guaranteedExistMap[guaranteedKey] = true
	}

	//  单篇 doc 参与到 context 的 chunk 长度上限，如果每篇必须出一个 chunk，则上限是平均，但最小是 chunk 本身的大小；否则是设定的默认值
	// 此为老逻辑，逐渐废弃，都用上面的保量策略
	avgChunkSizeLimit := chunkReRankConfig.TotalSize / len(items)
	if avgChunkSizeLimit < chunkReRankConfig.ValueSize {
		avgChunkSizeLimit = chunkReRankConfig.ValueSize
	}
	actualChunkSizeLimitPerDoc := lo.Ternary(chunkReRankConfig.EachDocHasChunk, avgChunkSizeLimit, chunkReRankConfig.ActualChunkSizeLimitPerDoc)

	// 处理chunk是否被used
	currTotal := guaranteedLength
	exceeded := false
	for idx, chunkResult := range chunkResultArr {
		// 如果指定了召回源ID，且当前item 不在指定召回源内 则不做处理
		if isUseCache && len(recallContentIds) > 0 && !lo.Contains(recallContentIds, chunkResult.item.GetBizItem().GetItemRecallContentId()) {
			// 如果已经饱和，剩下的 chunk 需要只保留一个作为展示使用，同时也可以塞分数排序用
			if itemChunkerMap[chunkResult.textId].UsedLength() == 0 {
				itemChunkerMap[chunkResult.textId].UseChunk(chunkResult.chunkMetaRes.ChunkId)
			}
			continue
		}

		// 尝试一把加入该chunk的长度，看是否超过限制
		deltaLength := itemChunkerMap[chunkResult.textId].GetUseChunkLengthByDelta(chunkResult.chunkMetaRes.ChunkId)
		if currTotal+deltaLength > chunkReRankConfig.TotalSize {
			exceeded = true
		}

		//  没有 exceeded 的 chunk 会被模型用上
		if !exceeded && util.IntInSlice(idx, scoreUsedIdxes) {
			// 单篇实际加入 prompt 的 chunk size 限制
			if itemChunkerMap[chunkResult.textId].UsedLength()+deltaLength <= actualChunkSizeLimitPerDoc {
				currTotal += deltaLength
				itemChunkerMap[chunkResult.textId].MarkActive()
				itemChunkerMap[chunkResult.textId].UseChunk(chunkResult.chunkMetaRes.ChunkId)
			}
		} else {
			// 如果已经饱和，剩下的 chunk 需要只保留一个作为展示使用，同时也可以塞分数排序用
			if itemChunkerMap[chunkResult.textId].UsedLength() == 0 {
				itemChunkerMap[chunkResult.textId].UseChunk(chunkResult.chunkMetaRes.ChunkId)
			}
		}
	}

	// 再把chunk根据 textId 合并回来，保障只有一个chunker对象
	uniqItemsChunkers := lo.UniqBy(chunkResultArr, func(item *itemChunkerMeta) int {
		return item.chunkMetaRes.TextId
	})

	// 有效的 chunker 数量
	usedCount := 0
	usedContentUnicodeLength := 0
	for _, itemsChunker := range uniqItemsChunkers {
		if itemChunkerMap[itemsChunker.textId].UsedLength() == 0 {
			continue
		}
		chunkRes := itemChunkerMap[itemsChunker.textId].Chunks()
		itemsChunker.item.GetBizItem().Text = chunkRes.MergeChunk
		itemsChunker.item.GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallScore = float64(chunkRes.MaxScore)
		itemsChunker.item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used = itemChunkerMap[itemsChunker.textId].IsActive()
		itemsChunker.item.GetBizItem().ChatTextTurnoverType = entities.ChatMappingTypeRecallChunk
		if itemChunkerMap[itemsChunker.textId].IsActive() {
			usedCount++
			usedContentUnicodeLength += util.UnicodeLen(itemsChunker.item.GetBizItem().Text)
		}
		// 如果召回源 包含答主自身 则直接默认使用喂给模型
		if lo.Contains(itemsChunker.item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KbSources, conf.KbSourceAuthorSelf) {
			itemsChunker.item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used = true
			// 如果是重答 且不在当前缓存中 则self默认不使用
			if isUseCache && len(recallContentIds) > 0 && !lo.Contains(recallContentIds, itemsChunker.item.GetBizItem().GetItemRecallContentId()) {
				itemsChunker.item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used = false
			}
		}
		resp = append(resp, itemsChunker.item)
	}

	// 先按照 Used 排序，把 used == True 的放在前面，然后内部再按照分数降序排序
	sort.Slice(resp, func(i, j int) bool {
		itemI := resp[i].GetBizItem().GetItemMeta().GetRecallSourceInfo()
		itemJ := resp[j].GetBizItem().GetItemMeta().GetRecallSourceInfo()

		if itemI.Used != itemJ.Used {
			return itemI.Used
		}
		return itemI.RecallScore > itemJ.RecallScore
	})

	// 打点 & 记录 tracing
	// 召回源数量
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank_v2.length", requestCtx.GetBizContext().Scenes()), float64(len(resp)))
	// 切chunk数量
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank_v2.chunk_length", requestCtx.GetBizContext().Scenes()), float64(len(itemMap)))
	// 有效的chunk数量
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank_v2.used_length", requestCtx.GetBizContext().Scenes()), float64(usedCount))
	// 有效的chunk unicode 长度
	statsd.TimeInMilliseconds(fmt.Sprintf(macro.OriginCommonStatsPrefix+".rerank_v2.used_content_unicode_length", requestCtx.GetBizContext().Scenes()), float64(usedContentUnicodeLength))

	s.saveTracing(requestCtx, resp)
	return resp, nil
}

// handleScoreScale 根据 tag 条件对分数乘上对应的缩放系数
func (s *KbRecallChunkAndScoreLogic) handleScoreScale(item *data_frame.ItemData[entities.Item], score float32, scoreScaleByTag string) float32 {
	if scoreScaleByTag == "" || item == nil {
		return score
	}

	// 解析配置：tagKey:tagValue:multiplier
	scoreScaleMap := make(map[string]float64) // key: tagKey:tagValue, value: multiplier
	scoreScaleList := strings.Split(scoreScaleByTag, ",")
	for _, scoreScaleKV := range scoreScaleList {
		scoreScaleSlice := strings.Split(scoreScaleKV, ":")
		if len(scoreScaleSlice) != 3 {
			continue
		}
		tagKey := scoreScaleSlice[0]
		tagValue := scoreScaleSlice[1]
		multiplier, err := strconv.ParseFloat(scoreScaleSlice[2], 64)
		if err != nil {
			continue
		}
		key := fmt.Sprintf("%s:%s", tagKey, tagValue)
		scoreScaleMap[key] = multiplier
	}

	// 检查item是否匹配tag条件（匹配到第一个条件就应用系数，参考 handlePriority 的逻辑）
	tagInfo := item.GetBizItem().GetItemMeta().TagInfo
	for key, multiplier := range scoreScaleMap {
		keyParts := strings.Split(key, ":")
		if len(keyParts) != 2 {
			continue
		}
		tagKey := keyParts[0]
		tagValue := keyParts[1]
		if graphUtil.GetTagValueString(tagInfo, tagKey) == tagValue {
			// 匹配到条件，应用系数并返回
			return float32(math.Min(float64(score)*multiplier, 1.0))
		}
	}

	return score
}

func (s *KbRecallChunkAndScoreLogic) saveTracing(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], chunks []*data_frame.ItemData[entities.Item]) {
	var rerankItems []*proto.RerankItem

	for _, item := range chunks {
		recallItem := &proto.RerankItem{
			DocId:     item.GetBizItem().ItemMeta.DocId,
			DocType:   item.GetBizItem().ItemMeta.DocType.String(),
			Title:     item.GetBizItem().ItemMeta.GetTitle(),
			Url:       item.GetBizItem().ItemMeta.Url,
			Chunk:     item.GetBizItem().Text,
			Score:     item.GetBizItem().ItemMeta.GetRecallSourceInfo().RecallScore,
			IsLlmUsed: item.GetBizItem().GetItemMeta().GetRecallSourceInfo().Used,
		}
		rerankItems = append(rerankItems, recallItem)
	}

	requestCtx.GetBizContext().GetMiddleProcess().Reranks = rerankItems
}

// curve 函数内部会做分数倒序，返回原始可用 index
func curve(scores []float64, threshold float64) []int {
	if len(scores) < 1 {
		return []int{}
	}
	if threshold == 0 {
		return lo.Map(scores, func(_ float64, i int) int {
			return i
		})
	}

	// Create a slice of structs to keep track of original indices
	type scoreWithIndex struct {
		score float64
		index int
	}

	// Create array of score-index pairs
	scoreIndices := make([]scoreWithIndex, len(scores))
	for i, score := range scores {
		scoreIndices[i] = scoreWithIndex{score: score, index: i}
	}

	// Sort in descending order by score
	sort.Slice(scoreIndices, func(i, j int) bool {
		return scoreIndices[i].score > scoreIndices[j].score
	})

	// Apply curve logic on sorted scores
	usedIdx := []int{}
	mean := scoreIndices[0].score
	for idx, si := range scoreIndices {
		if mean-si.score > threshold {
			break
		}
		usedIdx = append(usedIdx, si.index) // Store original index

		// Calculate new mean using original scores
		sum := 0.0
		for j := 0; j <= idx; j++ {
			sum += scoreIndices[j].score
		}
		mean = sum / float64(idx+1)
	}

	return usedIdx
}

// 处理保量队列，针对挂载 author、base、doc 的，要确保每个 author 下保量一个、每个 base 下保量一个、每个 doc 保量一个
func getGuaranteedKey(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], item *data_frame.ItemData[entities.Item]) string {
	for _, authorId := range requestCtx.GetBizContext().GetCurrReferenceMount().GetMountMembers() {
		if item.GetBizItem().GetItemMeta().AuthorId == authorId {
			return fmt.Sprintf("author_%d", authorId)
		}
	}
	for _, base := range requestCtx.GetBizContext().GetCurrReferenceMount().GetMountBases() {
		if item.GetBizItem().GetItemMeta().GetRecallSourceInfo().KnowledgeBaseId == base.GetKnowledgeBaseId() &&
			item.GetBizItem().GetItemMeta().GetRecallSourceInfo().PersonalKnowledgeBaseType == base.GetKnowledgeBaseType() {
			return fmt.Sprintf("base_%d_%d", base.GetKnowledgeBaseType(), base.GetKnowledgeBaseId())
		}
	}
	for _, doc := range requestCtx.GetBizContext().GetCurrReferenceMount().GetMountDocs() {
		if item.GetBizItem().GetItemMeta().DocId == doc.GetDocId() &&
			item.GetBizItem().GetItemMeta().DocType == model.GetDocTypeByZhiDaType(doc.GetDocType()) {
			return fmt.Sprintf("doc_%d_%s", doc.GetDocId(), doc.GetDocType())
		}
	}

	return ""
}

// rerankByQueryMerge 将多个 queryMerge 召回的 chunk 进行混合重排序
// 重排方式为 reciprocal rank fusion，即假如有 3 个 queryMerge，其下结果分别为A1-n、B1-m、C1-k，则取 A1、B1、C1、A2、B2、C2...分层选取
func rerankByQueryMerge(itemList []*itemChunkerMeta) []*itemChunkerMeta {
	// Group items by RecallQueryMerge
	queryMergeGroups := make(map[string][]*itemChunkerMeta)
	for _, item := range itemList {
		queryMerge := item.item.GetBizItem().GetItemMeta().GetRecallSourceInfo().RecallQueryMerge
		queryMergeGroups[queryMerge] = append(queryMergeGroups[queryMerge], item)
	}

	// If only one group, return as is
	if len(queryMergeGroups) <= 1 {
		return itemList
	}

	// Get max length of any group
	maxLen := 0
	for _, group := range queryMergeGroups {
		if len(group) > maxLen {
			maxLen = len(group)
		}
	}

	// Perform RRF by taking items from each group in round-robin fashion
	result := make([]*itemChunkerMeta, 0, len(itemList))
	for i := 0; i < maxLen; i++ {
		for _, group := range queryMergeGroups {
			if i < len(group) {
				result = append(result, group[i])
			}
		}
	}

	return result
}
