package generate

import (
	"context"
	"regexp"
	"sort"
	"strings"
	"time"

	"git.in.zhihu.com/go/cafe/config"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	rpcImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	basicUtil "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	graphUtil "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type CiteHandler struct {
	minCnSenteceLength          int
	minEnSenteceLength          int
	maxCiteCountPerSentenceHigh int
	maxCiteCountPerSentenceLow  int
	citeScoreHighThreshold      float32
	citeScoreLowThreshold       float32
	citeScoreAutoCutThreshold   float32
	citeRerankThreshold         float32
	candidateCiteSnippets       []*entities.CiteSnippet
	klaraHttpClient             rpc.KlaraHttp
	klaraUrl                    rpc.KlaraServiceUrl
	embeddingModelName          string
	klaraRerankerUrl            rpc.KlaraServiceUrl
	rerankerModelName           string
	sentenceSplitter            *basicUtil.SentenceSplitter
}

const m3EmbeddingDim = 1792

func NewCiteHandler(ctx context.Context, items []*data_frame.ItemData[entities.Item], isInit bool) *CiteHandler {

	senMinCnLength := cast.ToInt(config.GetString("stream_chat.cite.sen_min_cn_length", "10"))
	senMinEnLength := cast.ToInt(config.GetString("stream_chat.cite.sen_min_en_length", "5"))
	maxCountHigh := cast.ToInt(config.GetString("stream_chat.cite.max_count_high", "5"))
	maxCountLow := cast.ToInt(config.GetString("stream_chat.cite.max_count_low", "3"))
	scoreHighThreshold := cast.ToFloat32(config.GetString("stream_chat.cite.cite_score_threshold_high", "0.92"))
	scoreLowThreshold := cast.ToFloat32(config.GetString("stream_chat.cite.cite_score_threshold_low", "0.85"))
	citeScoreAutoCutThreshold := cast.ToFloat32(config.GetString("stream_chat.cite.cite_score_auto_cut_threshold", "0.005"))
	citeRerankThreshold := cast.ToFloat32(config.GetString("stream_chat.cite.cite_rerank_threshold_v2", "0"))
	obj := &CiteHandler{
		minCnSenteceLength:          senMinCnLength,
		minEnSenteceLength:          senMinEnLength,
		maxCiteCountPerSentenceHigh: maxCountHigh,
		maxCiteCountPerSentenceLow:  maxCountLow,
		citeScoreHighThreshold:      scoreHighThreshold,
		citeScoreLowThreshold:       scoreLowThreshold,
		citeScoreAutoCutThreshold:   citeScoreAutoCutThreshold,
		citeRerankThreshold:         citeRerankThreshold,
		klaraHttpClient:             rpcImpl.NewKlaraHttpImpl(2 * time.Second),
		klaraUrl:                    rpc.KlaraServiceUrlZhiEmb,
		embeddingModelName:          "zhi-embedding-prompt-zhida",
		klaraRerankerUrl:            rpc.KlaraServiceUrlBgeRerank,
		rerankerModelName:           "bge-reranker-v2-m3",
		sentenceSplitter:            basicUtil.NewSentenceSplitter(),
	}

	if isInit {
		obj.candidateCiteSnippets = obj.initCiteSnippets(ctx, items)
	} else {
		obj.candidateCiteSnippets = []*entities.CiteSnippet{}
	}
	return obj

}

/*
根据某个 doc 的 chunk，初始化角标文档
*/
func (c *CiteHandler) initCiteSnippets(ctx context.Context, items []*data_frame.ItemData[entities.Item]) []*entities.CiteSnippet {
	if len(items) < 1 {
		return []*entities.CiteSnippet{}
	}

	// 先分句
	allCiteSnippets := make([]*entities.CiteSnippet, 0)
	for docIndex, itemT := range items {
		item := itemT.GetBizItem()
		used := item.GetItemMeta().GetRecallSourceInfo().Used
		rank := 0
		authorLevel := graphUtil.GetCreatorDocLevelTagValue(item.GetItemMeta().AuthorTagInfo)
		_, isWhiteListAuthor := graphUtil.GetStarAuthorIdNames()[item.GetItemMeta().AuthorId]
		if isWhiteListAuthor {
			rank = 2
		} else if authorLevel >= 4 {
			rank = 1
		}

		// 当前 chunk 没有被模型引用
		if !used {
			continue
		}

		// 分句
		chunk := item.Text
		sentenceWithIndexs := c.sentenceSplitter.SplitText(chunk, 20)

		// 太短的不需要
		if len(sentenceWithIndexs) < 1 {
			continue
		}
		sentences := lo.Map(sentenceWithIndexs, func(item basicUtil.SentenceWithIndex, _ int) string {
			return item.Content
		})

		lastShortSentence := ""
		for idx, sentence := range sentences {

			isEnglishOnly := c.isEnglishOnly(sentence)

			// 过滤掉较短的句子
			if (!isEnglishOnly && basicUtil.CountChineseChars(sentence) < c.minCnSenteceLength) ||
				(isEnglishOnly && len(strings.Split(sentence, " ")) < c.minEnSenteceLength) {
				lastShortSentence = sentence
				continue
			}

			lastSent := ""
			if idx > 0 {
				if len(lastShortSentence) > 0 && idx > 1 {
					lastSent = sentences[idx-2]
				} else {
					lastSent = sentences[idx-1]
				}
			}

			nextSent := ""
			if idx < len(sentences)-1 {
				nextSent = sentences[idx+1]
			}

			// 构成高亮摘要
			lastSentRune := []rune(strings.TrimSpace(lastSent))
			nextSentRune := []rune(strings.TrimSpace(nextSent))
			if len(lastSentRune) > c.minCnSenteceLength {
				lastSent = "..." + string(lastSentRune[len(lastSentRune)-c.minCnSenteceLength:])
			}
			if len(nextSentRune) > c.minCnSenteceLength {
				nextSent = string(nextSentRune[:c.minCnSenteceLength]) + "..."
			}

			abstract := lastSent + "<highlight>" + lastShortSentence + sentence + "</highlight>" + nextSent
			citeId := docIndex*10000 + idx

			citeSnippet := &entities.CiteSnippet{
				DocIndex:    docIndex + 1,
				CiteId:      citeId,
				DocSentence: lastShortSentence + sentence,
				DocAbstract: abstract,
				Rank:        rank,
			}
			allCiteSnippets = append(allCiteSnippets, citeSnippet)
			lastShortSentence = ""
		}
	}

	// 查 embedding
	docSentences := lo.Map(allCiteSnippets, func(citeSnippet *entities.CiteSnippet, _ int) string {
		return citeSnippet.DocSentence
	})
	embeddings := c.klaraHttpClient.ConcurrentInferEmbedding(ctx, c.klaraUrl, docSentences, c.embeddingModelName)

	for idx, citeSnippet := range allCiteSnippets {
		citeSnippet.Embedding = embeddings[idx]
	}

	allCiteSnippets = lo.Filter(allCiteSnippets, func(citeSnippet *entities.CiteSnippet, _ int) bool {
		return len(citeSnippet.Embedding) == m3EmbeddingDim
	})

	return allCiteSnippets
}

/*
给定回答中的某一句，找出最匹配的角标文档
*/
func (c *CiteHandler) getMatchedCites(ctx context.Context, sentence string) []*entities.CiteSnippet {
	sentsEmbed := c.klaraHttpClient.ConcurrentInferEmbedding(ctx, c.klaraUrl, []string{sentence}, c.embeddingModelName)
	//log.Infof(ctx, "sentence: %s", sentence)
	if len(sentsEmbed) == 0 || len(sentsEmbed[0]) != m3EmbeddingDim {
		return []*entities.CiteSnippet{}
	}
	curSentEmbed := sentsEmbed[0]

	candidateCiteSnippets := c.candidateCiteSnippets

	citeSnippetWithScores := make(chan *entities.CiteSnippet, len(candidateCiteSnippets))
	cosineWG := safe_group.NewGroupWithTimeout("processCite", 1000).SetLimit(100)
	for _, citeSnippet := range candidateCiteSnippets {
		newCiteSnippet := citeSnippet
		snippetEmbedding := citeSnippet.Embedding

		// 余弦相似度
		cosineWG.Go(func() error {
			cosineScore, err := basicUtil.CosineByDefIgnoreNormalize01(curSentEmbed, snippetEmbedding, 0)
			if err != nil {
				log.Warnf(ctx, "CosineByDefIgnoreNormalize error: %v", err)
				cosineScore = 0.0
			}
			newCiteSnippet.Score = cosineScore
			citeSnippetWithScores <- newCiteSnippet

			return nil
		})

	}

	go func() {
		wgErr := cosineWG.Wait()
		if wgErr != nil {
			log.Warnf(ctx, "Cosine Chan Wait Err => %v", wgErr)
		}

		close(citeSnippetWithScores)
	}()

	allSnippets := make([]*entities.CiteSnippet, 0)
	for snippet := range citeSnippetWithScores {
		allSnippets = append(allSnippets, snippet)
	}

	// 按打分从大到小返回
	sort.Slice(allSnippets, func(i, j int) bool {
		return allSnippets[i].Score > allSnippets[j].Score
	})

	usedDocs := make(map[int]*entities.CiteSnippet)
	selectedCiteSnippets := make([]*entities.CiteSnippet, 0)

	// 大于high 阈值的 snippet 优先
	for _, snippet := range allSnippets {
		// 已小于阈值，截断
		if snippet.Score < float64(c.citeScoreHighThreshold) {
			break
		}

		// 如果当前的 doc 已被引用，则跳过当前，只保留第一个即可
		if _, exists := usedDocs[snippet.DocIndex]; exists {
			continue
		}

		// 单句插入的角标个数已达上限
		if len(selectedCiteSnippets) >= c.maxCiteCountPerSentenceHigh {
			break
		}

		// 加入
		selectedCiteSnippets = append(selectedCiteSnippets, snippet)
		usedDocs[snippet.DocIndex] = snippet
	}

	if len(selectedCiteSnippets) == 0 {
		meanScore := 0.0
		sumScore := 0.0
		for idx, snippet := range allSnippets {
			sumScore += snippet.Score
			meanScore = sumScore / float64(idx+1)
			// autocut
			if meanScore-snippet.Score > float64(c.citeScoreAutoCutThreshold) {
				break
			}

			// 已小于阈值，截断
			if snippet.Score < float64(c.citeScoreLowThreshold) {
				break
			}

			// 如果当前的 doc 已被引用，则跳过当前，只保留第一个即可
			if _, exists := usedDocs[snippet.DocIndex]; exists {
				continue
			}

			// 单句插入的角标个数已达上限
			if len(selectedCiteSnippets) >= c.maxCiteCountPerSentenceLow {
				break
			}

			// 加入
			selectedCiteSnippets = append(selectedCiteSnippets, snippet)
			usedDocs[snippet.DocIndex] = snippet
		}
	}

	// 后处理，先按 rank 排，再按相关性得分排
	sort.Slice(selectedCiteSnippets, func(i, j int) bool {
		m := selectedCiteSnippets[i]
		n := selectedCiteSnippets[j]
		if m.Rank != n.Rank {
			return m.Rank > n.Rank
		}
		return m.Score > n.Score
	})

	return selectedCiteSnippets[:zrecUtil.Min(len(selectedCiteSnippets), c.maxCiteCountPerSentenceHigh)]
}

func (c *CiteHandler) getHighlightCites(ctx context.Context, sentence string, docIds []int) []*entities.CiteSnippet {
	candidateCiteSnippets := make([]*entities.CiteSnippet, 0)
	for _, cite := range c.candidateCiteSnippets {
		if lo.Contains(docIds, cite.DocIndex) {
			candidateCiteSnippets = append(candidateCiteSnippets, cite)
		}
	}

	docSentences := lo.Map(candidateCiteSnippets, func(citeSnippet *entities.CiteSnippet, _ int) string {
		return citeSnippet.DocSentence
	})

	var similarScores = c.klaraHttpClient.BatchInferPairwiseScoreBySize(ctx, rpc.KlaraServiceUrlBgeRerank, rpc.KlaraRerankRequest{
		Query: sentence,
		Texts: docSentences,
	}, 1)

	if len(similarScores) == len(candidateCiteSnippets) {
		for i, item := range candidateCiteSnippets {
			score := similarScores[i]
			item.Score = float64(score)
		}
	} else {
		log.Warnf(ctx, "scores len not equal to textParts len")
	}

	// Group by docIndex and keep highest scoring cite for each doc
	docIndexMap := make(map[int]*entities.CiteSnippet)
	for _, cite := range candidateCiteSnippets {
		if existing, ok := docIndexMap[cite.DocIndex]; !ok || cite.Score > existing.Score {
			docIndexMap[cite.DocIndex] = cite
		}
	}

	// Convert map values back to slice
	result := make([]*entities.CiteSnippet, 0, len(docIndexMap))
	for _, cite := range docIndexMap {
		result = append(result, cite.CopyCite())
	}

	// 后处理，先按 rank 排，再按相关性得分排
	sort.Slice(result, func(i, j int) bool {
		m := result[i]
		n := result[j]
		if m.Rank != n.Rank {
			return m.Rank > n.Rank
		}
		return m.Score > n.Score
	})

	return result

}

var englishOnlyPattern = regexp.MustCompile(`[^a-zA-Z0-9\s.,!?;:'"()\-]`)

func (c *CiteHandler) isEnglishOnly(text string) bool {
	// 匹配除了英文字母、数字、标点符号和空格以外的任何字符
	return !englishOnlyPattern.MatchString(text)
}
