package util

import (
	"crypto/md5"
	"crypto/rand"
	"encoding/hex"
	"math"
	"regexp"
	"strings"
	"unicode"

	"git.in.zhihu.com/go/ztext/ztext"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/modelapi/dto"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/cespare/xxhash/v2"
	"github.com/samber/lo"
)

// StringLen 中文2，字母&标点符号1个
func StringLen(s string) int {
	cnt := 0
	for _, r := range s {
		if unicode.IsNumber(r) || (r >= 'A' && r <= 'Z') || (r >= 'a' && r <= 'z') || unicode.IsSpace(r) || unicode.IsPunct(r) {
			cnt += 1
		} else {
			cnt += 2
		}
	}
	return cnt
}

func UnicodeLen(str string) int {
	var r = []rune(str)
	return len(r)
}

func UnicodeWordLen(str string) int {
	var r = []rune(str)
	length := 0
	for _, char := range r {
		// 判断是否为单字节字符（英文或数字）
		if unicode.IsLetter(char) && char <= 127 || unicode.IsNumber(char) {
			length += 1 // 单字节字符算半个长度，累加到1
		} else {
			length += 2 // 非单字节字符算2
		}
	}
	return length / 2
}

func UnicodeIndex(str, substr string) int {
	result := strings.Index(str, substr)
	if result > 0 {
		prefix := []byte(str)[0:result]
		rs := []rune(string(prefix))
		result = len(rs)
	}
	return result
}

func UnicodeSubstr(str string, start, length int) string {
	return string(lo.Slice([]rune(str), start, start+length))
}

func StringSafeSlice(str string, start, end int) string {
	if start < 0 {
		start = 0
	}
	if end > len(str) {
		end = len(str)
	}
	return str[start:end]
}

func ToPlainText(s string) (string, error) {
	o, err := ztext.NewZOutputText(s)
	if err != nil {
		return "", err
	}
	return o.PlainText(), nil
}

func SplitText(text []rune, chunkSize int, chunkMaxSize int, chunkOverlap int) []string {
	windows := [][]rune{}
	start := 0
	end := 0
	for start < len(text) {
		end = start + chunkSize
		// 往后找第一个句子结束位置
		sentEnd := findEndPos(lo.Slice(text, end, math.MaxInt))
		if sentEnd != -1 {
			end += sentEnd + 1
		}
		windows = append(windows, lo.Slice(text, start, end))
		start = end - chunkOverlap
		if start < 0 {
			start = 0
		}
		// 往前找第一个句子开始位置
		sentEndStart := findEndPos(lo.Slice(text, start, math.MaxInt))
		if sentEndStart != -1 {
			start += sentEndStart + 1
		}
	}
	// 超过 chunkSize 的 过滤掉
	return lo.Map(windows, func(window []rune, _ int) string {
		return string(window[:zrecUtil.Min(chunkMaxSize, len(window))])
	})
}
func findEndPos(text []rune) int {
	pattern := regexp.MustCompile(`[。？！?!\n]`)
	matches := pattern.FindStringIndex(string(text))
	if len(matches) > 0 {
		return len([]rune(string(text)[:matches[0]]))
	} else {
		return -1
	}
}

// GetSurroundingSentences 返回文本1在文本2中第n次出现的周围句子(前后各一句)
// text1: 要查找的文本
// text2: 要查找的文本
// order: 第几次出现 从1开始
func GetSurroundingSentences(text1, text2 string, order int, unmatchedLimit int) string {
	// 因为 order 从 1 开始，下方配套程序时按照 0 开始的索引，所以这里需要减 1
	// 比较简单粗暴的处理方案
	order--
	if order < 0 {
		return ""
	}

	// 补偿文本2末尾的换行符
	isEnd := strings.HasSuffix(text2, text1)
	if isEnd {
		text2 += "\n"
	}

	// 使用正则表达式分割句子，保留分隔符
	re := regexp.MustCompile(`([^。？！?!\n]+[。？！?!\n])`)
	sentences := re.FindAllString(text2, -1)

	// 找到所有包含 text1 的句子索引
	var occurrences []int
	for i, s := range sentences {
		if strings.Contains(s, text1) {
			occurrences = append(occurrences, i)
		}
	}

	// 检查是否有足够的出现次数
	if order >= len(occurrences) {
		// 补偿如果text2中包含text1，但实际通过正则没有匹配出来，则其实为当前text没有断句，则整段文本喂入模型
		if strings.Contains(text2, text1) {
			return UnicodeSubstr(text2, 0, zrecUtil.Min(unmatchedLimit, UnicodeLen(text2)))
		}
		return ""
	}

	// 获取指定 order 的句子索引
	currentSentenceIndex := occurrences[order]

	// 确定要返回的句子范围
	startIndex := currentSentenceIndex
	endIndex := currentSentenceIndex

	// 尝试获取三个句子，但在开始和结束位置允许两个句子
	for endIndex-startIndex+1 < 3 {
		if startIndex > 0 {
			startIndex--
		}
		if endIndex-startIndex+1 < 3 && endIndex < len(sentences)-1 {
			endIndex++
		}
		// 如果已经包含了所有可能的句子或者在开始/结束位置有两个句子，则停止
		if (startIndex == 0 && endIndex-startIndex+1 >= 2) ||
			(endIndex == len(sentences)-1 && endIndex-startIndex+1 >= 2) ||
			(startIndex == 0 && endIndex == len(sentences)-1) {
			break
		}
	}

	// 构建结果字符串
	var result strings.Builder
	for i := startIndex; i <= endIndex; i++ {
		result.WriteString(sentences[i])
	}

	return strings.TrimSpace(result.String())
}

// ConvertToRemovedSymbolHash 移除str中所有标点符号，然后再hash到int64
func ConvertToRemovedSymbolHash(str string) int64 {
	str = RemoveSymbol(str)
	return HashToInt64(str)
}

func HashToInt64(str string) int64 {
	return int64(xxhash.Sum64String(str))
}

func MD5(str string) string {
	hash := md5.Sum([]byte(str))
	return hex.EncodeToString(hash[:])
}

func SecureRandString(n int) (string, error) {
	bytes := make([]byte, n)
	if _, err := rand.Read(bytes); err != nil {
		return "", err
	}
	return hex.EncodeToString(bytes), nil // 生成十六进制字符串
}

var regp = regexp.MustCompile(`[\pP]*`)

func RemoveSymbol(content string) string {
	content = regp.ReplaceAllString(content, "")
	content = strings.ReplaceAll(content, "\n", "")
	content = strings.ReplaceAll(content, " ", "")
	return content
}

// GetIsvcAndNameSpaceFromKlaraUrl url示例：
// http://bge-reranker-ai-zhida-online.jeeves-agi.klara.pek02.rack.zhihu.com
// http://zhi-reranker-zhida.jeeves-agi.klara-isolated-2.pek02.rack.zhihu.com
func GetIsvcAndNameSpaceFromKlaraUrl(url string) (isvcName string, nameSpace string, cluster string) {
	subUrl := strings.Split(url, ".")
	if len(subUrl) < 4 || !strings.HasPrefix(subUrl[2], "klara") {
		isvcName = "default"
		nameSpace = "default"
		return
	}

	isvc, _ := strings.CutPrefix(subUrl[0], "http://")
	isvc, _ = strings.CutPrefix(isvc, "https://")

	isvcName = isvc
	nameSpace = subUrl[1]
	cluster = subUrl[3]
	return
}

func GetIsvcAndNameSpace(model *dto.ModelEndpoint) (isvcName string, nameSpace string, cluster string) {
	isvcName, nameSpace, cluster = GetIsvcAndNameSpaceFromKlaraUrl(model.BaseURL)
	if isvcName == "default" {
		isvcName = model.Model
		if model.BaseURL == macro.ModelProxyUrl {
			nameSpace = "model-proxy"
		}
	}
	return
}

// IsChinese 判断字符串中是否包含中文
var chineseRegex = regexp.MustCompile("[\u4e00-\u9fa5]")
var japaneseRegex = regexp.MustCompile("[\u3040-\u309F\u30A0-\u30FF]")

func IsChinese(s string) bool {
	if !chineseRegex.MatchString(s) {
		return false
	}
	japaneseCount := len(japaneseRegex.FindAllString(s, -1))
	if float64(japaneseCount) > float64(UnicodeLen(s))*0.1 {
		return false
	}
	return true
}

// CountChineseChars 计算字符串中中文字符的个数
func CountChineseChars(text string) int {
	count := 0
	for _, r := range text {
		// 使用 unicode.Han 判断是否为汉字
		if unicode.Is(unicode.Han, r) {
			count++
		}
	}
	return count
}

func SafeTruncateJSON(jsonStr string, maxLength int) string {
	// 去除末尾的反斜杠
	cleaned := regexp.MustCompile(`\\+$`).ReplaceAllString(jsonStr, "")

	if UnicodeLen(cleaned) <= maxLength {
		return cleaned
	}

	// 截断到指定长度
	truncated := UnicodeSubstr(cleaned, 0, maxLength)

	// 再次去除可能产生的末尾反斜杠
	return regexp.MustCompile(`\\+$`).ReplaceAllString(truncated, "")
}
