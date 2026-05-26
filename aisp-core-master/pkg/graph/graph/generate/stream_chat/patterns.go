package stream_chat

import "regexp"

// Stream Chat 相关正则表达式定义

// SentencePattern 句子分隔符匹配
var SentencePattern = regexp.MustCompile("[。？?!！\n]")

var (
	// PartialCitationPat 匹配可能被截断的 citation 片段，包括被括号/方括号/花括号包裹的情况
	// 用于检测流式输出中不完整的 citation 标记
	PartialCitationPat = regexp.MustCompile(`([(\[{]?\[citation:\d+|[(\[{]?\[citation:|[(\[{]?\[citation|[(\[{]?\[citatio|[(\[{]?\[citati|[(\[{]?\[citat|[(\[{]?\[cita|[(\[{]?\[cit|[(\[{]?\[ci|[(\[{]?\[c|[(\[{]?\[)$`)

	// CitationParser 从 citation 标记中提取数字，支持括号/方括号/花括号包裹
	// 匹配格式如: [citation:1], ([citation:2]), {[citation:3]}
	CitationParser = regexp.MustCompile(`[(\[{]?\[citation:(\d+)\][)\]}]?`)

	// RemoveCitation 匹配完整的 [citation:N] 标记，用于移除
	RemoveCitation = regexp.MustCompile(`\[citation:\d+\]`)
)

var (
	// PartialProductPat 匹配可能被截断的 product 片段
	// 用于检测流式输出中不完整的 product 标记
	PartialProductPat = regexp.MustCompile(`\|?\s*<product[^>]*$|\|?\s*<produ[^>]*$|\|?\s*<prod[^>]*$|\|?\s*<pro[^>]*$|\|?\s*<pr[^>]*$|\|?\s*<p[^>]*$|\|?\s*<product[^>]*>[^<]*$|\|?\s*<product[^>]*>[^<]*</p(?:r(?:o(?:d(?:u(?:c(?:t)?)?)?)?)?)?$|\|?\s*<product[^>]*>[^<]*</$|\|?\s*<p\s*$|\|?\s*<\s*$|\|\s*\*\*$|\|\s*\*$|\|\*\*$|\|\*$`)

	// ThinkProductPat 匹配思考阶段的 product 标签处理
	ThinkProductPat = regexp.MustCompile(`<$|<\s*$|<p[^>]*$|<pr[^>]*$|<pro[^>]*$|<prod[^>]*$|<produ[^>]*$|<product[^>]*$|</$|</p[^>]*$|</pr[^>]*$|</pro[^>]*$|</prod[^>]*$|</produ[^>]*$|</product[^>]*$`)

	// ProductParser 从 product 标签中提取内容
	// 只匹配简单的 <product>XX</product> 格式，不包含嵌套标签
	ProductParser = regexp.MustCompile(`[(\[{]?<product>([^<]*)</product>[)\]}]?`)

	// RemoveProduct 匹配完整的 <product>content</product> 标记，用于移除
	RemoveProduct = regexp.MustCompile(`<product>[^<]*</product>`)
)
