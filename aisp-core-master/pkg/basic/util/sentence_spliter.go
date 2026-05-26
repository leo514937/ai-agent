package util

import (
	"regexp"
	"strings"
	"unicode/utf8"
)

// SentenceSplitter 用于分割句子的结构体
type SentenceSplitter struct {
	protectedPatterns []*regexp.Regexp
}

func NewSentenceSplitter() *SentenceSplitter {
	patterns := []string{
		`\.{3,}`,                       // 连续的省略号 ...
		`(?:\.\s+){2,}\.`,              // 带空格的省略号 . . .
		`\d+\.\d+%`,                    // 百分比数字，例如 50.5%
		`\d+\.\d+`,                     // 小数
		`\[\d+\]\.`,                    // 引用格式 [1].
		`\(\d{4}\)\.`,                  // 引用格式 (2020).
		`et al\.`,                      // 引用格式 et al.
		`\d{4}\.\d{1,2}\.\d{1,2}`,      // YYYY.MM.DD
		`\d{1,2}\.\d{1,2}\.\d{4}`,      // DD.MM.YYYY
		`\d{1,2}\.[A-Za-z]{3,}\.\d{4}`, // DD.Month.YYYY
		`(?:[A-Z]\.)+[A-Z]?`,           // 缩写
		`[a-zA-Z0-9]+\.[a-zA-Z]{2,}`,   // 网址
		`\d+\.\s`,                      // 列点标号（如 "1. "）
	}

	compiledPatterns := make([]*regexp.Regexp, len(patterns))
	for i, pattern := range patterns {
		compiledPatterns[i] = regexp.MustCompile(pattern)
	}

	return &SentenceSplitter{
		protectedPatterns: compiledPatterns,
	}
}

// 表示句子及其在原文中的索引
type SentenceWithIndex struct {
	Content string
	Start   int
	End     int
}

// SplitText 分割文本为句子，确保结果严格来自原文
// 处理各种省略号形式，无论出现在何种环境中
// 参数:
//
//	text: 待分割的文本
//	minLength: 每个分句的最小长度，默认为20
//
// 返回:
//
//	[]SentenceWithIndex: 分句及其对应的索引位置
func (sp *SentenceSplitter) SplitText(text string, minLength int) []SentenceWithIndex {
	if minLength <= 0 {
		minLength = 20 // 默认最小长度
	}

	// 1. 找出所有需要保护的区域（避免在这些区域内部分句）
	protectedRegions := []struct {
		Start int
		End   int
	}{}

	// 处理各种括号对
	brackets := []struct {
		Left  rune
		Right rune
	}{
		{'{', '}'},
		{'(', ')'},
		{'[', ']'},
	}

	// 查找所有括号对及其内容
	for _, bracket := range brackets {
		var stack []int
		for i, r := range text {
			if r == bracket.Left {
				stack = append(stack, i)
			} else if r == bracket.Right && len(stack) > 0 {
				start := stack[len(stack)-1]
				stack = stack[:len(stack)-1]
				if len(stack) == 0 { // 确保只处理最外层括号对
					protectedRegions = append(protectedRegions, struct {
						Start int
						End   int
					}{Start: start, End: i + utf8.RuneLen(r)})
				}
			}
		}
	}

	// 2. 用正则表达式查找需要保护的模式
	for _, re := range sp.protectedPatterns {
		matches := re.FindAllStringIndex(text, -1)
		for _, match := range matches {
			protectedRegions = append(protectedRegions, struct {
				Start int
				End   int
			}{Start: match[0], End: match[1]})
		}
	}

	// 3. 合并重叠区域
	// 按开始位置排序
	for i := 0; i < len(protectedRegions); i++ {
		for j := i + 1; j < len(protectedRegions); j++ {
			if protectedRegions[i].Start > protectedRegions[j].Start {
				protectedRegions[i], protectedRegions[j] = protectedRegions[j], protectedRegions[i]
			}
		}
	}

	// 合并重叠区域
	if len(protectedRegions) > 0 {
		merged := []struct {
			Start int
			End   int
		}{protectedRegions[0]}

		for i := 1; i < len(protectedRegions); i++ {
			prev := merged[len(merged)-1]
			curr := protectedRegions[i]

			// 如果当前区域与前一个重叠或紧邻，合并它们
			if curr.Start <= prev.End {
				if curr.End > prev.End {
					merged[len(merged)-1].End = curr.End
				}
			} else {
				merged = append(merged, curr)
			}
		}
		protectedRegions = merged
	}

	// 4. 定义分句标点
	sentenceEnders := map[rune]bool{
		'。':  true,
		'.':  true,
		'!':  true,
		'！':  true,
		'?':  true,
		'？':  true,
		'…':  true,
		'\n': true,
	}

	// 5. 分割句子
	var sentences []SentenceWithIndex
	var currentSentence []rune
	sentenceStart := 0
	isInSentence := false

	for i, r := range text {
		if !isInSentence {
			sentenceStart = i
			isInSentence = true
		}
		currentSentence = append(currentSentence, r)

		// 检查当前字符是否在受保护区域内
		isProtected := false
		for _, region := range protectedRegions {
			if i >= region.Start && i < region.End {
				isProtected = true
				break
			}
		}

		// 如果是句尾标点且不在受保护区域内，或者是特殊标点
		if sentenceEnders[r] {
			if !isProtected || r == '\n' || r == '。' || r == '!' || r == '！' || r == '?' || r == '？' || r == '…' {
				if len(currentSentence) > 0 {
					content := strings.TrimSpace(string(currentSentence))
					if content != "" {
						sentences = append(sentences, SentenceWithIndex{
							Content: content,
							Start:   sentenceStart,
							End:     i + utf8.RuneLen(r),
						})
					}
					currentSentence = nil
					isInSentence = false
				}
			}
		}
	}

	// 处理最后一个句子
	if len(currentSentence) > 0 {
		content := strings.TrimSpace(string(currentSentence))
		if content != "" {
			sentences = append(sentences, SentenceWithIndex{
				Content: content,
				Start:   sentenceStart,
				End:     len(text),
			})
		}
	}

	// 6. 合并短句子
	if len(sentences) > 0 {
		var mergedSentences []SentenceWithIndex
		i := 0
		for i < len(sentences) {
			current := sentences[i]

			// 如果当前句子小于最小长度且不是最后一个句子
			for utf8.RuneCountInString(current.Content) < minLength && i+1 < len(sentences) {
				i++
				nextSentence := sentences[i]
				current.Content = current.Content + " " + nextSentence.Content
				current.End = nextSentence.End
			}

			mergedSentences = append(mergedSentences, current)
			i++
		}

		return mergedSentences
	}

	return []SentenceWithIndex{}
}
