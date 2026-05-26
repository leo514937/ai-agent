package rerank_util

import (
	"context"
	"regexp"
	"sort"
	"strings"
	"unicode/utf8"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type BoundaryRegexEnum string

func (b BoundaryRegexEnum) String() string {
	return string(b)
}

const (
	BoundaryRegexByNone           BoundaryRegexEnum = "."
	BoundaryRegexBySentence       BoundaryRegexEnum = "[。？！?!\\n]|\\.+"
	BoundaryRegexByParagraph      BoundaryRegexEnum = "\\n+"
	boundaryInnerRegexByParagraph BoundaryRegexEnum = "^[0-9]+$"
)

var regexMap = map[BoundaryRegexEnum]*regexp.Regexp{}

func init() {
	regexMap[BoundaryRegexByNone] = regexp.MustCompile(BoundaryRegexByNone.String())
	regexMap[BoundaryRegexBySentence] = regexp.MustCompile(BoundaryRegexBySentence.String())
	regexMap[BoundaryRegexByParagraph] = regexp.MustCompile(BoundaryRegexByParagraph.String())
	regexMap[boundaryInnerRegexByParagraph] = regexp.MustCompile(boundaryInnerRegexByParagraph.String())
}

// chunkSpan 切换span的unicode index（内部使用）
type chunkSpan struct {
	beginUnicodeIndex int
	endUnicodeIndex   int
}

// ChunkKeyContent chunkKey（内部使用）
type ChunkKeyContent struct {
	TextId       int
	ChunkId      int
	ChunkKeyText string
}

// ChunkMetaRes Chunk 元数据结果返回
type ChunkMetaRes struct {
	TextId  int
	ChunkId int
	Score   float32
}

// ChunkRes 合并后结果返回
type ChunkRes struct {
	TextId     int
	Chunks     []string
	Scores     []float32
	MergeChunk string
	MaxScore   float32
}

// DocumentChunker 文章切块处理器
type DocumentChunker struct {
	ctx                 context.Context
	text                *string // text 原始文本指针
	textId              int     // textId 文本ID（for循环下标），用于快速定位
	bounds              []int   // bounds 切割边界
	kSize               int
	kLSize              int
	kRSize              int
	KStep               int
	vSize               int
	vLSize              int
	vRSize              int
	kOffset             float64
	kSpans              []chunkSpan                 // kSpans
	vSpans              []chunkSpan                 // vSpans
	indicesAndScores    *util.SyncMap[int, float32] // indicesAndScores chunk索引 与 分数map（主要用于 mergeSpan）
	usedIndices         map[int]bool                // usedIndices 使用的索引(用map来去重)
	active              bool                        // active 标识 是否需要被模型采用
	boundaryRegex       BoundaryRegexEnum           // boundaryRegex 边界正则
	textUnicodeIndexArr *[]int                      // textIndex 文本索引
}

// NewDocumentChunker 创建一个新的文章处理器
// 注: 每一个text 都需要有一个处理器来维护状态
func NewDocumentChunker(
	ctx context.Context,
	text *string,
	textId int,
	kSize int,
	KStep int,
	vSize int,
	kOffset float64,
	boundaryRegex BoundaryRegexEnum) *DocumentChunker {
	// 防止非法创建异常 chunker
	if kSize <= 0 || KStep <= 0 || vSize <= 0 || kOffset <= 0 {
		return nil
	}

	chunker := &DocumentChunker{
		ctx:              ctx,
		text:             text,
		textId:           textId,
		kSize:            kSize,
		KStep:            KStep,
		vSize:            vSize,
		kOffset:          kOffset,
		boundaryRegex:    boundaryRegex,
		kSpans:           make([]chunkSpan, 0),
		vSpans:           make([]chunkSpan, 0),
		indicesAndScores: util.NewSyncMap[int, float32](),
		usedIndices:      make(map[int]bool),
	}

	// 预制text unicode 索引
	chunker.createTextIndex()
	// 计算边界
	chunker.bounds = chunker.getBounds(*chunker.text, boundaryRegex, kSize)
	chunker.kLSize = chunker.kSize / 2
	chunker.kRSize = chunker.kSize - chunker.kLSize
	chunker.vLSize = cast.ToInt(chunker.kOffset * cast.ToFloat64(chunker.vSize))
	chunker.vRSize = chunker.vSize - chunker.vLSize
	length := len(*chunker.textUnicodeIndexArr)
	// 处理Spans
	end := zrecUtil.Max(length-chunker.vRSize, 0) + chunker.KStep
	for i := 0; i < end; i += chunker.KStep {
		chunker.kSpans = append(chunker.kSpans, chunkSpan{
			beginUnicodeIndex: zrecUtil.Max(i-chunker.kLSize, 0),
			endUnicodeIndex:   zrecUtil.Min(i+chunker.kRSize, length-1),
		})
		chunker.vSpans = append(chunker.vSpans, chunkSpan{
			beginUnicodeIndex: zrecUtil.Max(i-chunker.vLSize, 0),
			endUnicodeIndex:   zrecUtil.Min(i+chunker.vRSize, length-1),
		})
	}
	return chunker
}

// getBounds 获取切割边界
func (d *DocumentChunker) getBounds(text string, boundaryRegex BoundaryRegexEnum, maxLen int) []int {
	// 使用更高效的内存分配策略
	textRunes := []rune(text)
	estimatedBoundaries := len(textRunes) / 100 // 预估边界数量
	bounds := make([]int, 0, estimatedBoundaries)
	bounds = append(bounds, 0)

	// 获取正则表达式，如果不存在则使用默认的句子分割正则
	currRegex := regexMap[boundaryRegex]
	if currRegex == nil {
		// 如果找不到对应的正则表达式，使用默认的句子分割正则
		currRegex = regexMap[BoundaryRegexBySentence]
		if currRegex == nil {
			// 如果连默认的正则都没有，说明初始化出现问题
			// 这里可以添加日志记录
			return bounds
		}
	}

	// 使用更高效的方式处理匹配
	matches := currRegex.FindAllStringIndex(text, -1)
	if len(matches) == 0 {
		return bounds
	}

	// 优化runeStarts的构建
	runeStarts := make([]int, 0, len(textRunes))
	var currentByte int
	for i := 0; i < len(textRunes); i++ {
		runeStarts = append(runeStarts, currentByte)
		currentByte += utf8.RuneLen(textRunes[i])
	}
	totalRunes := len(runeStarts)

	// 优化匹配结果的处理，减少内存分配
	formatMatches := make([][]int, 0, len(matches))
	for _, m := range matches {
		startByte, endByte := m[0], m[1]
		runeStart := d.byteIndexToRuneIndex(startByte, runeStarts)
		runeEnd := d.byteIndexToRuneIndex(endByte, runeStarts)
		formatMatches = append(formatMatches, []int{runeStart, runeEnd})
	}

	// 优化边界计算逻辑
	lastBound := 0
	for _, m := range formatMatches {
		start, end := m[0], m[1]

		// 检查句号是否在数字之间
		if boundaryRegex.String() == BoundaryRegexBySentence.String() {
			subStr := d.getSubstringFromRunes(text, runeStarts, start, end-start)
			if subStr == "." && start > 0 && end < totalRunes {
				prevChar := d.getSubstringFromRunes(text, runeStarts, start-1, 1)
				nextChar := d.getSubstringFromRunes(text, runeStarts, start+1, 1)
				if d.isDigit(prevChar) && d.isDigit(nextChar) {
					continue
				}
			}
		}

		// 优化边界添加逻辑
		if maxLen > 0 && maxLen < end-lastBound {
			for i := lastBound; i < end; i += maxLen {
				bounds = append(bounds, i)
			}
		}
		if lastBound != end {
			bounds = append(bounds, end)
			lastBound = end
		}
	}

	// 最后一个字符可能不是句号
	if lastBound != totalRunes {
		bounds = append(bounds, totalRunes)
	}
	return bounds
}

// byteIndexToRuneIndex 将字节索引转换为rune索引
func (d *DocumentChunker) byteIndexToRuneIndex(bytePos int, runeStarts []int) int {
	index := sort.Search(len(runeStarts), func(i int) bool {
		return runeStarts[i] > bytePos
	})
	return index - 1
}

// getSubstringFromRunes 根据rune索引获取子字符串
func (d *DocumentChunker) getSubstringFromRunes(text string, runeStarts []int, start, length int) string {
	if start < 0 || start >= len(runeStarts) {
		return ""
	}
	startByte := runeStarts[start]
	var endByte int
	if start+length < len(runeStarts) {
		endByte = runeStarts[start+length]
	} else {
		endByte = len(text)
	}
	return text[startByte:endByte]
}

// createTextIndex 执行unicode对于text的索引
func (d *DocumentChunker) createTextIndex() {
	// 使用更高效的内存分配方式
	textRunes := []rune(*d.text)
	runeToByteIndex := make([]int, 0, len(textRunes))

	var currentByte int
	for i := 0; i < len(textRunes); i++ {
		runeToByteIndex = append(runeToByteIndex, currentByte)
		currentByte += utf8.RuneLen(textRunes[i])
	}
	// 添加文本末尾的索引
	runeToByteIndex = append(runeToByteIndex, len(*d.text))
	d.textUnicodeIndexArr = &runeToByteIndex
}

// getRuneTextToByteIndex 获取UnicodeText
func (d *DocumentChunker) getRuneTextToByteIndex(startRune, endRune int) (string, bool) {
	runeToByteIndex := *d.textUnicodeIndexArr
	// 确保索引在合法范围内，避免越界
	if startRune < 0 || startRune >= len(runeToByteIndex) || endRune < 0 || endRune >= len(runeToByteIndex) {
		// 可以根据需要处理错误，例如跳过或记录日志
		return "", false
	}
	startByte := runeToByteIndex[startRune]
	endByte := runeToByteIndex[endRune]
	chunkText := (*d.text)[startByte:endByte]
	return chunkText, true
}

// isDigit 用于 getBounds 判断是否数字位
func (d *DocumentChunker) isDigit(s string) bool {
	regex := regexMap[boundaryInnerRegexByParagraph]
	if regex == nil {
		return false
	}
	return regex.MatchString(s)
}

// Keys 返回Keys
func (d *DocumentChunker) Keys() []ChunkKeyContent {
	// 预分配结果切片的容量，避免多次内存分配
	result := make([]ChunkKeyContent, 0, len(d.kSpans))
	for cid, span := range d.kSpans {
		chunkText, isGetChunkText := d.getRuneTextToByteIndex(span.beginUnicodeIndex, span.endUnicodeIndex)
		if !isGetChunkText {
			continue
		}
		result = append(result, ChunkKeyContent{
			TextId:       d.textId,
			ChunkId:      cid,
			ChunkKeyText: chunkText,
		})
	}
	return result
}

// lBound 找左临界边
func (d *DocumentChunker) lBound(i int) int {
	index := sort.Search(len(d.bounds), func(j int) bool {
		return d.bounds[j] > i
	})
	if index > 0 {
		index--
	}
	return d.bounds[index]
}

// rBound 找右临界边
func (d *DocumentChunker) rBound(i int) int {
	index := sort.Search(len(d.bounds), func(j int) bool {
		return d.bounds[j] >= i
	})
	if index < len(d.bounds) {
		return d.bounds[index]
	}
	return d.bounds[len(d.bounds)-1]
}

// mergedSpans 合并 span
func (d *DocumentChunker) mergedSpans(usedIndices map[int]bool) ([]chunkSpan, [][]int) {
	if len(usedIndices) == 0 {
		return nil, nil
	}
	var spans []chunkSpan
	var spanIDs [][]int
	var current chunkSpan
	var currentIDs []int
	first := true

	indicesArr := make([]int, 0)
	for index := range usedIndices {
		indicesArr = append(indicesArr, index)
	}
	// Score 正序排序
	sort.Ints(indicesArr)

	for _, index := range indicesArr {
		span := d.vSpans[index]
		span = chunkSpan{d.lBound(span.beginUnicodeIndex), d.rBound(span.endUnicodeIndex)}
		if first {
			current = span
			currentIDs = []int{index}
			first = false
			continue
		}

		if current.endUnicodeIndex >= span.beginUnicodeIndex {
			current.endUnicodeIndex = span.endUnicodeIndex
			currentIDs = append(currentIDs, index)
		} else {
			spans = append(spans, current)
			spanIDs = append(spanIDs, currentIDs)
			current = span
			currentIDs = []int{index}
		}
	}
	spans = append(spans, current)
	spanIDs = append(spanIDs, currentIDs)
	return spans, spanIDs
}

func (d *DocumentChunker) Chunks() *ChunkRes {
	res := &ChunkRes{}

	if len(d.usedIndices) == 0 {
		return res
	}

	spans, spanIDs := d.mergedSpans(d.usedIndices)
	var chunks []string
	for _, span := range spans {
		chunkText, isGetChunkText := d.getRuneTextToByteIndex(span.beginUnicodeIndex, span.endUnicodeIndex)
		if !isGetChunkText {
			continue
		}
		chunks = append(chunks, chunkText)
	}

	maxScores := make([]float32, 0)
	for i := range spans {
		ids := spanIDs[i]
		var maxScore float32
		for _, i := range ids {
			if d.indicesAndScores.GetByIgnore(i) > maxScore {
				maxScore = d.indicesAndScores.GetByIgnore(i)
			}
		}
		maxScores = append(maxScores, maxScore)
	}

	res.TextId = d.textId
	// 原始chunks
	res.Chunks = chunks
	// 合并 chunk
	res.MergeChunk = strings.Join(lo.Map(chunks, func(item string, index int) string {
		return strings.TrimSpace(item)
	}), "\n...\n")
	res.Scores = maxScores
	// 最大分
	res.MaxScore = lo.Max(maxScores)
	return res
}

// MarkActive 设置当前chunk 被选中喂给模型
func (d *DocumentChunker) MarkActive() {
	d.active = true
}

// IsActive 判断是否被选中 喂给模型
func (d *DocumentChunker) IsActive() bool {
	return d.active
}

// GetChunksMeta 获取chunks元数据（回调）
// 回调方法由调用方填写，可自由控制并发度，如果后期batchSize比较好用的话，还可以适当增加batchSize
func (d *DocumentChunker) GetChunksMeta(query string, callback func(ctx context.Context, query string, chunksText []string) []float32) []*ChunkMetaRes {
	chunksText := make([]string, 0)
	for _, item := range d.Keys() {
		chunksText = append(chunksText, item.ChunkKeyText)
	}

	chunksMetaResArr := make([]*ChunkMetaRes, 0)
	scores := callback(d.ctx, query, chunksText)
	if len(scores) == len(chunksText) {
		for i, item := range d.Keys() {
			d.indicesAndScores.Set(item.ChunkId, scores[i])
			chunksMetaResArr = append(chunksMetaResArr, &ChunkMetaRes{
				TextId:  d.textId,
				ChunkId: item.ChunkId,
				Score:   scores[i],
			})
		}
	}
	return chunksMetaResArr
}

// SetChunkScore 手动回填chunk score
func (d *DocumentChunker) SetChunkScore(chunkId int, score float32) *ChunkMetaRes {
	d.indicesAndScores.Set(chunkId, score)
	return &ChunkMetaRes{
		TextId:  d.textId,
		ChunkId: chunkId,
		Score:   score,
	}
}

// UseChunk 使用当前Chunk
func (d *DocumentChunker) UseChunk(chunkId int) {
	d.usedIndices[chunkId] = true
}

// GetUseChunkLengthByDelta 尝试获取尝试加入当前chunk后的length
func (d *DocumentChunker) GetUseChunkLengthByDelta(chunkId int) int {
	usedIndicesDelta := make(map[int]bool)
	for index := range d.usedIndices {
		usedIndicesDelta[index] = true
	}
	usedIndicesDelta[chunkId] = true
	newLen := d.innerUsedLength(usedIndicesDelta)
	currentLen := d.UsedLength()
	return newLen - currentLen
}

// UsedLength 当前已用长度
func (d *DocumentChunker) UsedLength() int {
	return d.innerUsedLength(d.usedIndices)
}

func (d *DocumentChunker) innerUsedLength(usedIndices map[int]bool) int {
	if len(usedIndices) == 0 {
		return 0
	}
	totalChunkLen := 0
	mergedSpans, _ := d.mergedSpans(usedIndices)
	for _, span := range mergedSpans {
		totalChunkLen += span.endUnicodeIndex - span.beginUnicodeIndex
	}
	return totalChunkLen
}
