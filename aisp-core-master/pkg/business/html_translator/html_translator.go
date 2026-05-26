package html_translator

import (
	"context"
	"fmt"
	"regexp"
	"strings"
	"sync/atomic"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_biz/aisp_core_translate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/klara_model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	zrecUtil "git.in.zhihu.com/zrec/zrec-framework/pkg/tools/util"
	"github.com/PuerkitoBio/goquery"
	"github.com/samber/lo"
	"golang.org/x/net/html"
)

// htmlTranslatedMark 已翻译标签标识
var htmlTranslatedTagMark = "data-aisp-t-original"
var htmlPattern = regexp.MustCompile(`<[a-z]+[^>]*>.*?</[a-z]+>|<[a-z]+[^>]*/>`)
var specialCharacterPattern = regexp.MustCompile("^[~`!@#$￥…%^&*()_\\-+={}\\[\\]|:：;、\"“'<>《》,.?/\\\\]+$")

// 定义常见的标题规律模式
var titlePatterns = []titlePattern{
	{"数字加点", regexp.MustCompile(`^\d+\.\s`), "1. 标题"},
	{"数字加括号", regexp.MustCompile(`^\d+\)\s`), "1) 标题"},
	{"数字加横线", regexp.MustCompile(`^\d+-\s`), "1- 标题"},
	{"小写字母加点", regexp.MustCompile(`^[a-z]\.\s`), "a. 标题"},
	{"小写字母加括号", regexp.MustCompile(`^[a-z]\)\s`), "a) 标题"},
	{"小写字母加横线", regexp.MustCompile(`^[a-z]-\s`), "a- 标题"},
	{"大写字母加点", regexp.MustCompile(`^[A-Z]\.\s`), "A. 标题"},
	{"大写字母加括号", regexp.MustCompile(`^[A-Z]\)\s`), "A) 标题"},
	{"大写字母加横线", regexp.MustCompile(`^[A-Z]-\s`), "A- 标题"},
	{"罗马数字加点", regexp.MustCompile(`^[IVXLCDM]+\.\s`), "I. 标题"},
	{"罗马数字加括号", regexp.MustCompile(`^[IVXLCDM]+\)\s`), "I) 标题"},
	{"罗马数字加横线", regexp.MustCompile(`^[IVXLCDM]+-\s`), "I- 标题"},
	{"中文序号", regexp.MustCompile(`^[一二三四五六七八九十百千万]+、`), "一、标题"},
	{"自定义分隔符", regexp.MustCompile(`^.+\s-\s\d+`), "标题 - 1"},
	{"方括号数字", regexp.MustCompile(`^\[\d+\]\s`), "[1] 标题"},
	{"阿拉伯语数字加点", regexp.MustCompile(`^[٠١٢٣٤٥٦٧٨٩]+\.\s`), "١. 标题"},
	{"日语序号", regexp.MustCompile(`^[①②③④⑤⑥⑦⑧⑨⑩]+\s`), "① 标题"},
	{"韩语序号", regexp.MustCompile(`^[가-힣]+\.\s`), "가. 标题"},
}

// titlePattern 定义标题规律的结构
type titlePattern struct {
	Name    string         // 规律名称
	Regex   *regexp.Regexp // 正则表达式
	Example string         // 示例
}

// translateAttribute 表示需要翻译的属性
type translateAttribute struct {
	Node     *goquery.Selection
	Original string
	AttrName string
}

// translateBlock 定义片段信息结构体，用于存储需要翻译的片段信息
type translateBlock struct {
	IsTranslated  bool         // 是否已翻译
	ParentElement *html.Node   // 当前片段的父元素
	TopElement    *html.Node   // 当前片段的顶部元素
	BottomElement *html.Node   // 当前片段的底部元素
	Nodes         []*html.Node // 当前片段包含的文本节点
}

// TranslateResponse 翻译内容结果
type TranslateResponse struct {
	SourceContent     string // 源文
	TranslatedContent string // 翻译后的文本
	IsAllTranslated   bool   // 是否全部翻译
}

type HtmlTranslator struct {
	sourceLanguage proto.Language
	targetLanguage proto.Language
	htmlStr        string
	htmlDocument   *goquery.Document
	// 最大重试次数
	retryMaxCount int
	// element 行内文本元素
	inlineElements []string
	// element 行内文本忽略元素
	inlineIgnoreElements []string
	// element 不需要翻译的元素
	noTranslateElements []string
	// element 不需要翻译的Selection表达式
	noTranslateSelections []string
	// element 可拆包元素
	unpackElements []string
	// element 标题元素
	titleElements []string
	// 异常翻译样本
	errorTranslateSample []string
	// 不翻译的文本正则
	noTranslateRegexps []*regexp.Regexp
	// block 占位符
	blockPlaceholderRegex *regexp.Regexp
	// 无头html 正则
	unWrapperHtmlBeginFlag string
	unWrapperHtmlEndFlag   string
	// title 示例参考数量
	titleExamplesMaxCount int
	// 错误数量
	failedCount atomic.Int64
	// cache
	tagCache          *util.SyncMap[string, string]
	attributeCache    *util.SyncMap[string, string]
	klaraModelService klara_model.KlaraModelService
	extraInfo         *proto.ExtraInfo
}

func NewHtmlTranslator(
	klaraService klara_model.KlaraModelService,
	htmlStr string,
	sourceLanguage proto.Language,
	targetLanguage proto.Language,
	noTranslateSelections []string,
	extraInfo *proto.ExtraInfo,
) (*HtmlTranslator, error) {
	// 初始化 HTML Reader
	document, err := goquery.NewDocumentFromReader(strings.NewReader(htmlStr))
	if err != nil {
		return nil, err
	}

	return &HtmlTranslator{
		extraInfo:         extraInfo,
		klaraModelService: klaraService,
		sourceLanguage:    sourceLanguage,
		targetLanguage:    targetLanguage,
		htmlStr:           htmlStr,
		htmlDocument:      document,
		inlineElements: []string{
			"a",
			"abbr",
			"acronym",
			"b",
			"bdo",
			"big",
			"br",
			"button",
			"cite",
			"pre",
			"code",
			"math",
			"dfn",
			"em",
			"i",
			"img",
			"input",
			"kbd",
			"label",
			"font",
			"map",
			"object",
			"output",
			"q",
			"samp",
			"script",
			"select",
			"small",
			"span",
			"strong",
			"sub",
			"sup",
			"textarea",
			"time",
			"tt",
			"var",
		},
		inlineIgnoreElements: []string{
			"br", "kbd", "wbr", "hr", "cite", "img", "object", "pre", "code", "math", "svg", "textarea", "equation",
		},
		unpackElements: []string{
			"b", "i", "span",
		},
		titleElements: []string{
			"h1", "h2", "h3", "h4", "h5", "h6",
		},
		noTranslateElements: []string{
			"script", "noscript", "style", "iframe",
		},
		noTranslateRegexps: []*regexp.Regexp{
			// [1] [2] 引用标
			regexp.MustCompile(`^\[\d+\]`),
			// 邮箱
			regexp.MustCompile(`^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$`),
			// URL
			regexp.MustCompile(`^(https?://)?(www\.)?([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/.*)?$`),
			// 全球手机号
			regexp.MustCompile(`^\+?[1-9]\d{1,14}$`),
			// 全球电话号
			regexp.MustCompile(`^\+?[1-9]\d{0,14}(-\d{1,4}){0,3}$`),
			// 单独运算符号
			regexp.MustCompile(`^(\+|\-|\*|\/|%|=|==|!=|>|>=|<|<=|&&|\|\||!)$`),
			// 数字+标点符号
			regexp.MustCompile(`^[0-9\.\,\;\:\!\?\+\-\*\/\%\=\>\<\&\|\!\(\)\[\]\{\}]*$`),
			// 特殊符号
			specialCharacterPattern,
		},
		errorTranslateSample: []string{
			"Please provide the complete text you want to be translated. The current input seems to be incomplete.",
		},
		noTranslateSelections:  lo.Uniq(noTranslateSelections),
		blockPlaceholderRegex:  regexp.MustCompile(`\{\{(.*?)\}\}`),
		unWrapperHtmlBeginFlag: "<html><head></head><body>",
		unWrapperHtmlEndFlag:   "</body></html>",
		titleExamplesMaxCount:  5,
		retryMaxCount:          3,
		tagCache:               util.NewSyncMap[string, string](),
		attributeCache:         util.NewSyncMap[string, string](),
	}, nil
}

func (h *HtmlTranslator) DoTranslate(ctx context.Context) (*TranslateResponse, error) {
	// 1. 先处理html 中标签中的文本翻译
	h.translateTags(ctx)
	// 2. 后处理html 中标签Attribute中的翻译
	h.translateAttributes(ctx)

	responseHtml, err := h.htmlDocument.Html()
	// 处理无头html，脱标签
	if strings.HasPrefix(responseHtml, h.unWrapperHtmlBeginFlag) && strings.HasSuffix(responseHtml, h.unWrapperHtmlEndFlag) {
		responseHtml = strings.TrimPrefix(responseHtml, h.unWrapperHtmlBeginFlag)
		responseHtml = strings.TrimSuffix(responseHtml, h.unWrapperHtmlEndFlag)
		responseHtml = strings.TrimSuffix(responseHtml, "\n")
	}

	// 如果不是 html 标签文本 则需要脱掉html转移字符
	if !h.isHTML(responseHtml) {
		responseHtml = html.UnescapeString(responseHtml)
	}

	return &TranslateResponse{
		SourceContent:     h.htmlStr,
		TranslatedContent: responseHtml,
		IsAllTranslated:   h.failedCount.Load() == 0,
	}, err
}

func (h *HtmlTranslator) translateTags(ctx context.Context) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "HtmlTranslator.translateTags",
	})
	retryCount := zrecUtil.Max(h.retryMaxCount, 1)
	// 1. 获取需要翻译的片段
	translateBlocks := h.getBlocksToTranslate(h.htmlDocument.Get(0))
	// 这里可以根据情况开并发
	for _, block := range translateBlocks {
		_ = h.translateBlock(block, func(txt string, pattern string, examples []string, completedExamples []string) (string, error) {
			var translateErr error
			var translateHTML = ""
			for i := 0; i < retryCount; i++ {
				translateErr = safe_group.SafeRun(func() error {
					modelArgs := klara_model.TranslateTemplate{
						Content:                     txt,
						TitlePattern:                pattern,
						TitleExample:                examples,
						TitleCompletedExamples:      completedExamples,
						TitleExampleFormat:          strings.Join(examples, "\n"),
						TitleCompletedExampleFormat: strings.Join(completedExamples, "\n"),
						SourceLanguage:              h.sourceLanguage.String(),
						TargetLanguage:              h.targetLanguage.String(),
					}
					if h.extraInfo != nil {
						modelArgs.DocId = h.extraInfo.DocId
						modelArgs.DocType = h.extraInfo.DocType
					}

					translateHTML = h.klaraModelService.TranslateHTML(ctx, modelArgs)
					return nil
				}, "translate tags panic")
				if translateErr == nil && translateHTML != "" {
					return translateHTML, nil
				}
				time.Sleep(100 * time.Millisecond)
			}
			if translateErr != nil {
				logger.Errorf(ctx, "调用模型错误 - ERR: %s", translateErr)
			}
			h.failedCount.Add(1)
			return translateHTML, translateErr
		})
	}

	// 2. 最终处理
	h.translateBlockSubmit(translateBlocks)
}

func (h *HtmlTranslator) translateAttributes(ctx context.Context) {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "HtmlTranslator.translateAttributes",
	})
	retryCount := zrecUtil.Max(h.retryMaxCount, 1)
	translateAttributes := h.getAttributesToTranslate()
	// 这里可以根据情况开并发
	for _, attribute := range translateAttributes {
		_ = h.translateAttribute(attribute, func(txt string) (string, error) {
			var translateErr error
			var translateHTML = ""
			for i := 0; i < retryCount; i++ {
				translateErr = safe_group.SafeRun(func() error {
					modelArgs := klara_model.TranslateTemplate{
						Content:        txt,
						SourceLanguage: h.sourceLanguage.String(),
						TargetLanguage: h.targetLanguage.String(),
					}
					if h.extraInfo != nil {
						modelArgs.DocId = h.extraInfo.DocId
						modelArgs.DocType = h.extraInfo.DocType
					}
					translateHTML = h.klaraModelService.TranslateHTML(ctx, modelArgs)
					return nil
				}, "translate tags panic")
				if translateErr == nil && translateHTML != "" {
					return translateHTML, nil
				}
				time.Sleep(100 * time.Millisecond)
			}
			if translateErr != nil {
				logger.Errorf(ctx, "调用模型错误 - ERR: %s", translateErr)
			}
			h.failedCount.Add(1)
			return translateHTML, translateErr
		})
	}
}

func (h *HtmlTranslator) getAttributesToTranslate() []translateAttribute {
	var attributesToTranslate []translateAttribute

	// 查找需要翻译的元素
	h.htmlDocument.Find("input[placeholder], textarea[placeholder]").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("placeholder", "")
		if strings.TrimSpace(txt) != "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: txt,
				AttrName: "placeholder",
			})
		}
	})

	h.htmlDocument.Find("area[alt], img[alt], img[data-caption], input[type='image'][alt]").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		// 如果是公式的image alt 则不做处理
		src := e.AttrOr("src", "")
		if strings.Contains(src, "equation") {
			return
		}
		txt := e.AttrOr("alt", "")
		if strings.TrimSpace(txt) != "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: txt,
				AttrName: "alt",
			})
		}
	})

	// 翻译知乎image caption
	h.htmlDocument.Find("img[data-caption]").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		// 如果是公式的image alt 则不做处理
		src := e.AttrOr("src", "")
		if strings.Contains(src, "equation") {
			return
		}
		txt := e.AttrOr("data-caption", "")
		if strings.TrimSpace(txt) != "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: txt,
				AttrName: "data-caption",
			})
		}
	})

	h.htmlDocument.Find("input[type='button'], input[type='submit'], input[type='reset']").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("value", "")
		if e.Is("input[type='submit']") && txt == "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: "Submit Query",
				AttrName: "value",
			})
		} else if e.Is("input[type='reset']") && txt == "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: "Reset",
				AttrName: "value",
			})
		} else if strings.TrimSpace(txt) != "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: txt,
				AttrName: "value",
			})
		}
	})

	h.htmlDocument.Find("[title]").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("title", "")
		if strings.TrimSpace(txt) != "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: txt,
				AttrName: "title",
			})
		}
	})

	h.htmlDocument.Find("sup[data-text]").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("data-text", "")
		if strings.TrimSpace(txt) != "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: txt,
				AttrName: "data-text",
			})
		}
	})

	h.htmlDocument.Find("sup[data-tooltip]").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("data-tooltip", "")
		if strings.TrimSpace(txt) != "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: txt,
				AttrName: "data-tooltip",
			})
		}
	})

	h.htmlDocument.Find("video[data-name]").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("data-name", "")
		if strings.TrimSpace(txt) != "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: txt,
				AttrName: "data-name",
			})
		}
	})

	h.htmlDocument.Find("i[aria-label]").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("aria-label", "")
		if strings.TrimSpace(txt) != "" {
			attributesToTranslate = append(attributesToTranslate, translateAttribute{
				Node:     e,
				Original: txt,
				AttrName: "aria-label",
			})
		}
	})

	h.htmlDocument.Find("meta[name='description'], meta[name='keywords']").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("content", "")
		attributesToTranslate = append(attributesToTranslate, translateAttribute{
			Node:     e,
			Original: txt,
			AttrName: "content",
		})
	})

	h.htmlDocument.Find("meta[name='twitter:title'], meta[name='twitter:description']").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("content", "")
		attributesToTranslate = append(attributesToTranslate, translateAttribute{
			Node:     e,
			Original: txt,
			AttrName: "content",
		})
	})

	h.htmlDocument.Find("meta[property='og:title'], meta[property='og:description'], meta[property='og:site_name']").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("content", "")
		attributesToTranslate = append(attributesToTranslate, translateAttribute{
			Node:     e,
			Original: txt,
			AttrName: "content",
		})
	})

	h.htmlDocument.Find("meta[itemprop='name'], meta[itemprop='description']").Each(func(i int, e *goquery.Selection) {
		if h.hasNoTranslate(e) {
			return
		}
		txt := e.AttrOr("content", "")
		attributesToTranslate = append(attributesToTranslate, translateAttribute{
			Node:     e,
			Original: txt,
			AttrName: "content",
		})
	})

	return attributesToTranslate
}

// getBlocksToTranslate 获取需要翻译的片段
func (h *HtmlTranslator) getBlocksToTranslate(root *html.Node) []translateBlock {
	if root == nil {
		return []translateBlock{}
	}

	// 初始化片段数组，初始时只有一个空片段
	blocksToTranslate := []translateBlock{
		{
			IsTranslated:  false,
			ParentElement: nil,
			TopElement:    nil,
			BottomElement: nil,
			Nodes:         []*html.Node{},
		},
	}

	// 当前片段的索引
	index := 0
	// 定义递归函数，用于遍历 HTML 树
	var getAllNodes func(node *html.Node, lastHTMLElement, lastSelectOrDataListElement *html.Node)
	getAllNodes = func(node *html.Node, lastHTMLElement, lastSelectOrDataListElement *html.Node) {
		// 如果当前节点是元素节点或文档节点
		if node.Type == html.ElementNode || node.Type == html.DocumentNode {
			// 如果是文档节点
			if node.Type == html.DocumentNode {
				lastHTMLElement = node // 更新最后一个 HTML 元素
				lastSelectOrDataListElement = nil
			} else if node.Type == html.ElementNode {
				nodeDataByLower := strings.ToLower(node.Data)
				lastHTMLElement = node // 更新最后一个 HTML 元素
				// 如果是 <select> 或 <datalist> 标签，特殊处理
				if nodeDataByLower == "select" || nodeDataByLower == "datalist" {
					lastSelectOrDataListElement = node
				}

				// 检查是否是需要忽略的标签或节点
				if lo.Contains(h.inlineIgnoreElements, nodeDataByLower) ||
					lo.Contains(h.noTranslateElements, nodeDataByLower) ||
					h.hasNoTranslate(h.htmlDocument.WrapNode(node)) {
					// 如果当前片段中已经有节点，则结束当前片段并开始新的片段
					if len(blocksToTranslate[index].Nodes) > 0 {
						blocksToTranslate[index].BottomElement = lastHTMLElement
						blocksToTranslate = append(blocksToTranslate, translateBlock{
							IsTranslated:  false,
							ParentElement: nil,
							TopElement:    nil,
							BottomElement: nil,
							Nodes:         []*html.Node{},
						})
						index++
					}
					return
				}

				// 检查是否包含需要忽略的自定义Selection
				for _, noTranslateSelection := range h.noTranslateSelections {
					if h.htmlDocument.Find(noTranslateSelection).IsNodes(node) {
						return
					}
				}
			}

			// 遍历子节点
			for childNode := node.FirstChild; childNode != nil; childNode = childNode.NextSibling {
				childNodeDataByLower := strings.ToLower(childNode.Data)
				// 如果子节点是元素节点
				if childNode.Type == html.ElementNode {
					lastHTMLElement = childNode
					// 如果是 select 或 datalist 标签，记录下来
					if childNodeDataByLower == "select" || childNodeDataByLower == "datalist" {
						lastSelectOrDataListElement = childNode
					}
				}

				// 如果子节点不是行内文本标签
				if !lo.Contains(h.inlineElements, childNodeDataByLower) {
					// 如果当前片段中已经有节点，则结束当前片段并开始新的片段
					if len(blocksToTranslate[index].Nodes) > 0 {
						blocksToTranslate[index].BottomElement = lastHTMLElement
						blocksToTranslate = append(blocksToTranslate, translateBlock{
							IsTranslated:  false,
							ParentElement: nil,
							TopElement:    nil,
							BottomElement: nil,
							Nodes:         []*html.Node{},
						})
						index++
					}

					// 递归处理子节点
					getAllNodes(childNode, lastHTMLElement, lastSelectOrDataListElement)

					// 如果当前片段中已经有节点，则结束当前片段并开始新的片段
					if len(blocksToTranslate[index].Nodes) > 0 {
						blocksToTranslate[index].BottomElement = lastHTMLElement
						blocksToTranslate = append(blocksToTranslate, translateBlock{
							IsTranslated:  false,
							ParentElement: nil,
							TopElement:    nil,
							BottomElement: nil,
							Nodes:         []*html.Node{},
						})
						index++
					}
				} else {
					// 如果是行内文本标签，递归处理子节点
					getAllNodes(childNode, lastHTMLElement, lastSelectOrDataListElement)
				}
			}

			// 如果当前片段的底部元素未设置，则设置为当前节点
			if blocksToTranslate[index].BottomElement == nil {
				blocksToTranslate[index].BottomElement = node
			}
		} else if node.Type == html.TextNode {
			// 如果当前节点是文本节点
			text := strings.TrimSpace(node.Data)
			if len(text) > 0 {
				// 如果当前片段的父元素未设置，则设置父元素
				if blocksToTranslate[index].ParentElement == nil {
					// 如果父节点是 <option>，设置为 <select> 或 <datalist>
					if node.Parent != nil && strings.ToLower(node.Parent.Data) == "option" && lastSelectOrDataListElement != nil {
						blocksToTranslate[index].ParentElement = lastSelectOrDataListElement
						blocksToTranslate[index].BottomElement = lastSelectOrDataListElement
						blocksToTranslate[index].TopElement = lastSelectOrDataListElement
					} else {
						// 向上查找父节点，直到找到非行内文本或非忽略的标签
						temp := node.Parent
						parentNodeDataByLower := strings.ToLower(temp.Data)
						for temp != nil && temp != root && (lo.Contains(h.inlineElements, parentNodeDataByLower) || lo.Contains(h.inlineIgnoreElements, parentNodeDataByLower)) {
							temp = temp.Parent
							parentNodeDataByLower = strings.ToLower(temp.Data)
						}
						blocksToTranslate[index].ParentElement = temp
					}
				}

				// 如果当前片段的顶部元素未设置，则设置顶部元素
				if blocksToTranslate[index].TopElement == nil {
					blocksToTranslate[index].TopElement = lastHTMLElement
				}

				blocksToTranslate[index].Nodes = append(blocksToTranslate[index].Nodes, node)
				blocksToTranslate[index].BottomElement = nil
			}
		}
	}

	// 开始递归遍历 HTML 树
	getAllNodes(root, nil, nil)

	// 如果最后一个片段是空的，则移除
	if len(blocksToTranslate) > 0 && len(blocksToTranslate[len(blocksToTranslate)-1].Nodes) == 0 {
		blocksToTranslate = blocksToTranslate[:len(blocksToTranslate)-1]
	}

	groupByParent := lo.GroupBy(blocksToTranslate, func(block translateBlock) *html.Node {
		return block.ParentElement
	})

	// 特殊处理 合并可拆包node
	for parentNode, childBlocks := range groupByParent {
		blocks := make([]translateBlock, 0)
		for i, childBlock := range childBlocks {
			if i == 0 {
				blocks = append(blocks, childBlock)
				continue
			}

			nodesTmp := make([]*html.Node, 0)
			for _, childNode := range childBlock.Nodes {
				// 如果当前节点的父节点是可拆包节点，则直接拆包挂在前一位node上 并删除当前node
				if childNode.Type == html.TextNode && childNode.Parent.Type == html.ElementNode && lo.Contains(h.unpackElements, strings.ToLower(childNode.Parent.Data)) {
					blocks[len(blocks)-1].Nodes[len(blocks[len(blocks)-1].Nodes)-1].Data += childNode.Data
					// 额外多拆一次 防止出现 span span
					if childNode.Parent.Parent != nil && childNode.Parent.Parent.Parent != nil && lo.Contains(h.unpackElements, strings.ToLower(childNode.Parent.Parent.Data)) {
						childNode.Parent.Parent.Parent.RemoveChild(childNode.Parent.Parent)
					} else if childNode.Parent.Parent != nil {
						childNode.Parent.Parent.RemoveChild(childNode.Parent)
					}
					continue
				} else if childNode.Type == html.TextNode && childNode.PrevSibling == blocks[len(blocks)-1].Nodes[len(blocks[len(blocks)-1].Nodes)-1] {
					blocks[len(blocks)-1].Nodes[len(blocks[len(blocks)-1].Nodes)-1].Data += childNode.Data
					if childNode.Parent != nil {
						childNode.Parent.RemoveChild(childNode)
					}
					continue
				}
				nodesTmp = append(nodesTmp, childNode)
			}
			if len(nodesTmp) > 0 {
				childBlock.Nodes = nodesTmp
				blocks = append(blocks, childBlock)
			}
		}
		groupByParent[parentNode] = blocks
	}

	translateBlocksResp := make([]translateBlock, 0)
	// 特殊处理 合并同级别 node
	for _, childBlocks := range groupByParent {
		var currNode *html.Node
		for i, childBlock := range childBlocks {
			if len(childBlock.Nodes) == 0 {
				continue
			}
			if i == 0 {
				translateBlocksResp = append(translateBlocksResp, childBlock)
				currNode = childBlock.Nodes[0]
			} else {
				isMatch := false
				temp := childBlock.Nodes[0].PrevSibling
				for temp != nil && temp != currNode {
					temp = temp.PrevSibling
					if temp == currNode {
						isMatch = true
						break
					}
				}

				if isMatch {
					translateBlocksResp[len(translateBlocksResp)-1].Nodes = append(translateBlocksResp[len(translateBlocksResp)-1].Nodes, childBlock.Nodes...)
				} else {
					translateBlocksResp = append(translateBlocksResp, childBlock)
				}
			}
		}
	}

	// 过滤掉非翻译的片段 TODO 有性能问题先下线
	//finalTranslateBlocksResp := make([]translateBlock, 0)
	//for _, tb := range translateBlocksResp {
	//LoopEnd:
	//	var isMatch = false
	//	for _, tNode := range tb.Nodes {
	//		text := strings.TrimSpace(tNode.Data)
	//		// 如果文本命中不翻译正则，直接退出
	//		for _, noTranslateRegexp := range h.noTranslateRegexps {
	//			if noTranslateRegexp.MatchString(text) {
	//				isMatch = true
	//				goto LoopEnd
	//			}
	//		}
	//	}
	//	if !isMatch {
	//		finalTranslateBlocksResp = append(finalTranslateBlocksResp, tb)
	//	}
	//}
	return translateBlocksResp
}

func (h *HtmlTranslator) translateBlockSubmit(blocks []translateBlock) {
	if len(blocks) == 0 {
		return
	}

	for _, block := range blocks {
		if block.Nodes == nil || len(block.Nodes) == 0 {
			continue
		}

		for _, node := range block.Nodes {
			selection := h.htmlDocument.FindNodes(node)
			res, isExist := selection.Attr(htmlTranslatedTagMark)
			if isExist {
				node.Data = res
				selection.RemoveAttr(htmlTranslatedTagMark)
			}
		}
	}
}

// translateAttribute 真实 翻译 Block
func (h *HtmlTranslator) translateBlock(block translateBlock, translateFunc func(txt string, pattern string, examples []string, completedExamples []string) (string, error)) error {
	if block.Nodes == nil || len(block.Nodes) == 0 {
		return nil
	}

	txt := ""
	for i, node := range block.Nodes {
		if i == 0 {
			txt += node.Data
			continue
		}
		txt += fmt.Sprintf(" {{%d}} %s", i-1, node.Data)
	}
	txt = h.removeExtraDelimiter(txt)
	if txt == "" || util.UnicodeLen(txt) == 0 {
		return nil
	}

	var pattern string
	var examples []string
	var completedExamples []string
	// 判断当前节点是否是标题类型，如果是则需要获取同类型标题
	if block.Nodes[0].Parent != nil && block.Nodes[0].Parent.Data != "" && lo.Contains(h.titleElements, strings.ToLower(block.Nodes[0].Parent.Data)) {
		var selection *goquery.Selection
		if block.Nodes[0].Parent.Parent != nil {
			selection = h.htmlDocument.FindNodes(block.Nodes[0].Parent.Parent).
				Find(strings.ToLower(block.Nodes[0].Parent.Data))
		} else {
			selection = h.htmlDocument.FindNodes(block.Nodes[0].Parent)
		}
		currTitle := block.Nodes[0].Data
		titles := make([]string, 0)
		selection.Each(func(i int, s *goquery.Selection) {
			for _, node := range s.Nodes {
				if node.FirstChild != nil && node.FirstChild.Type == html.TextNode {
					titles = append(titles, node.FirstChild.Data)
					translatedTitle, translatedTitleIsExist := h.htmlDocument.FindNodes(node.FirstChild).Attr(htmlTranslatedTagMark)
					if translatedTitleIsExist && translatedTitle != "" && util.UnicodeLen(translatedTitle) > 0 {
						completedExamples = append(completedExamples, translatedTitle)
					}
				}
			}
		})

		pattern, examples = h.detectGlobalTitlePatterns(titles, currTitle)

		// 补偿措施
		// 如果只匹配到自身 则尝试获取一下全局的同类型标签 如果能找到同一个规律则按照当前规律执行
		if len(titles) == 1 {
			reTryTitles := make([]string, 0)
			reTryTranslatedTitles := make([]string, 0)
			h.htmlDocument.Find(strings.ToLower(block.Nodes[0].Parent.Data)).Each(func(i int, s *goquery.Selection) {
				for _, node := range s.Nodes {
					if node.FirstChild != nil && node.FirstChild.Type == html.TextNode {
						reTryTitles = append(reTryTitles, node.FirstChild.Data)
						translatedTitle, translatedTitleIsExist := h.htmlDocument.FindNodes(node).Attr(htmlTranslatedTagMark)
						if translatedTitleIsExist && translatedTitle != "" && util.UnicodeLen(translatedTitle) > 0 {
							reTryTranslatedTitles = append(reTryTranslatedTitles, translatedTitle)
						}
					}
				}
			})
			reTryPattern, reTryExamples := h.detectGlobalTitlePatterns(reTryTitles, currTitle)
			if reTryPattern != "" && len(reTryExamples) > 0 {
				pattern = reTryPattern
				examples = reTryExamples
				completedExamples = reTryTranslatedTitles
			}
		}
	}

	var res string
	var err error
	cacheTranslateHtml, isExistCache := h.tagCache.Get(txt)
	// 如果命中缓存
	if isExistCache && cacheTranslateHtml != "" {
		res = cacheTranslateHtml
		err = nil
	} else {
		res, err = translateFunc(txt, pattern, examples, completedExamples[0:zrecUtil.Min(len(completedExamples), h.titleExamplesMaxCount)])
	}
	if err != nil {
		return err
	}
	isTranslated := true
	// 判断翻译结果是否为空
	if res == "" {
		res = txt
		isTranslated = false
	} else {
		// 检测是否正确翻译
		for _, sample := range h.errorTranslateSample {
			if strings.Contains(res, sample) {
				res = txt
				isTranslated = false
			}
		}
	}

	// 判断首字母是否是特殊字符
	if util.UnicodeLen(txt) > 2 && util.UnicodeLen(res) > 2 {
		firstChar := util.UnicodeSubstr(txt, 0, 1)
		secondChar := util.UnicodeSubstr(txt, 1, 1)
		firstResChar := util.UnicodeSubstr(res, 0, 1)
		if specialCharacterPattern.MatchString(firstChar) && (!specialCharacterPattern.MatchString(firstResChar) || secondChar == firstResChar) {
			res = firstChar + res
		}
	}

	// 如果成功翻译 则保存缓存(如果是标题类 则不存储缓存，防止有同类型但不同规范的标题因为缓存 而受到污染)
	if isTranslated && !isExistCache && pattern == "" {
		h.tagCache.Set(txt, res)
	}

	placeholders := h.extractPlaceholders(res)
	for i, node := range block.Nodes {
		isMatch := false
		placeholder := ""
		if i < len(placeholders) {
			placeholder = placeholders[i]
			isMatch = true
		}
		if isMatch {
			// 去除尾部缓存 & html转义
			h.htmlDocument.FindNodes(node).SetAttr(htmlTranslatedTagMark, strings.TrimSuffix(placeholder, "\n"))
		} else {
			// 如果匹配不上则直接移除当前节点
			node.Parent.RemoveChild(node)
		}
	}
	return nil
}

// translateAttribute 真实 翻译 Attribute
func (h *HtmlTranslator) translateAttribute(attribute translateAttribute, translateFunc func(txt string) (string, error)) error {
	txt := h.removeExtraDelimiter(attribute.Original)
	if txt == "" {
		return nil
	}

	var res string
	var err error
	cacheTranslateHtml, isExistCache := h.attributeCache.Get(txt)
	if isExistCache && cacheTranslateHtml != "" {
		res = cacheTranslateHtml
		err = nil
	} else {
		res, err = translateFunc(txt)
	}
	if err != nil {
		return err
	}
	isTranslated := true

	// 判断翻译结果是否为空
	if res == "" {
		res = txt
		isTranslated = false
	} else {
		// 检测是否正确翻译
		for _, sample := range h.errorTranslateSample {
			if strings.Contains(res, sample) {
				res = txt
				isTranslated = false
			}
		}
	}

	// 判断首字母是否是特殊字符
	if util.UnicodeLen(txt) > 2 && util.UnicodeLen(res) > 2 {
		firstChar := util.UnicodeSubstr(txt, 0, 1)
		secondChar := util.UnicodeSubstr(txt, 1, 1)
		firstResChar := util.UnicodeSubstr(res, 0, 1)
		if specialCharacterPattern.MatchString(firstChar) && (!specialCharacterPattern.MatchString(firstResChar) || secondChar == firstResChar) {
			res = firstChar + res
		}
	}

	// 如果成功翻译 则保存缓存
	if isTranslated && !isExistCache {
		h.attributeCache.Set(txt, res)
	}

	attribute.Node.SetAttr(attribute.AttrName, res)
	return nil
}

// 工具函数：检查元素是否需要跳过翻译
func (h *HtmlTranslator) hasNoTranslate(elem *goquery.Selection) bool {
	if elem.HasClass("notranslate") || elem.AttrOr("translate", "") == "no" {
		return true
	}
	return false
}

// 工具函数：删除无用的换行符和空格，这可能会影响我们的语义
func (h *HtmlTranslator) removeExtraDelimiter(textContext string) string {
	// 替换所有换行符为一个空格
	textContext = strings.ReplaceAll(textContext, "\n", " ")
	// 使用正则表达式替换多个空格为一个空格
	re := regexp.MustCompile(` +`) // 匹配两个或更多的空格
	textContext = re.ReplaceAllString(textContext, " ")
	return textContext
}

// 工具函数：提取字符串中的 {{d}} 格式内容
func (h *HtmlTranslator) extractPlaceholders(input string) []string {
	spilt := "{{_,_}}"
	// 定义正则表达式
	placeholderRegex := regexp.MustCompile(`\{\{.*?\}\}`)
	// 使用正则表达式替换匹配的部分为空字符串
	cleaned := placeholderRegex.ReplaceAllString(input, spilt)
	// 使用空格分割字符串并去除多余空格
	// 这里使用 `strings.Fields` 来自动处理多个空格的情况
	parts := strings.Split(cleaned, spilt)
	if len(parts) == 0 {
		return []string{input}
	}
	return parts
}

// 工具函数：检测字符串列表的标题规律
func (h *HtmlTranslator) detectGlobalTitlePatterns(lines []string, currTitle string) (string, []string) {
	if len(lines) == 0 {
		return "", []string{}
	}

	dict := make(map[string][]string)
	// 遍历所有模式2
	for _, pattern := range titlePatterns {
		re := pattern.Regex
		var lineContents []string
		// 遍历每一行，检查是否符合当前模式
		for _, line := range lines {
			if re.MatchString(line) {
				lineContents = append(lineContents, line)
			}
		}
		dict[pattern.Name] = lineContents
	}

	for detectedPattern, exampleContents := range dict {
		for _, exampleContent := range exampleContents {
			if exampleContent == currTitle {
				return detectedPattern, exampleContents[0:zrecUtil.Min(h.titleExamplesMaxCount, len(exampleContents))]
			}
		}
	}
	return "", []string{}
}

// 工具函数：检测是不是HTML文本
func (h *HtmlTranslator) isHTML(s string) bool {
	s = strings.TrimSpace(s)

	// 检查常见HTML标记
	if strings.HasPrefix(s, "<!DOCTYPE html>") || strings.HasPrefix(s, "<!doctype html>") {
		return true
	}

	// 检查是否包含HTML标签
	if htmlPattern.MatchString(s) {
		return true
	}

	// 检查常见的HTML元素
	commonTags := []string{"<html", "<head", "<body", "<div", "<p", "<span", "<a ", "<img", "<table"}
	for _, tag := range commonTags {
		if strings.Contains(strings.ToLower(s), tag) {
			return true
		}
	}

	return false
}
