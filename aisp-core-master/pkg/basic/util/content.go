package util

import (
	"context"
	"strings"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"golang.org/x/net/html"
	"golang.org/x/net/html/atom"
)

func ContentHasEquation(content string) bool {
	return strings.Contains(content, "<equation>") || strings.Contains(content, "www.zhihu.com/equation")
}

func ContentFilterHtml(ctx context.Context, rawContent string) (string, error) {
	logger := log.WithField(ctx, "methodName", "contentFilterHtml")
	var content = rawContent
	if len(content) == 0 {
		return content, nil
	}

	//// 计算body 实际 length
	//aTextLength := 0
	//HTMLWalk(content, func(parent, node *html.Node) bool {
	//	if node == nil {
	//		return false
	//	}
	//
	//	if node.DataAtom != atom.A {
	//		return true
	//	}
	//	aTextLength += UnicodeLen(lo.Must(ToPlainText(NodeToHtml(node))))
	//	return false
	//})

	// 过滤 html body （去除超链接）
	body := HTMLFilter(content, func(node *html.Node) bool {
		if node == nil {
			return false
		}
		return node.DataAtom != atom.A
	})

	// 如果 TextLength > Filtered body Length, so continue
	bodyText, err := ToPlainText(body)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "ToPlainText error")
		return "", err
	}
	//if int64(aTextLength*2) > int64(UnicodeLen(bodyText)) {
	//	logger.Warn(ctx, "TextLength > Filtered body Length, so continue")
	//	return "", errors.New("textLength illegal")
	//}
	return bodyText, nil
}

func ContentHtml2Markdown(ctx context.Context, rawContent string) (string, error) {
	logger := log.WithField(ctx, "methodName", "contentFilterHtml")
	var content = rawContent
	if len(content) == 0 {
		return content, nil
	}

	// 如果 TextLength > Filtered body Length, so continue
	bodyText, err := ToPlainText(content)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "ToPlainText error")
		return "", err
	}

	return bodyText, nil
}

func removeScripts(node *html.Node) {
	if node.Type == html.ElementNode && node.Data == "script" {
		node.Parent.RemoveChild(node)
		return
	}
	for c := node.FirstChild; c != nil; c = c.NextSibling {
		removeScripts(c)
	}
}

func ContentFilterScripts(ctx context.Context, rawContent string) string {
	logger := log.WithField(ctx, "methodName", "contentFilterScripts")
	// 解析HTML
	doc, err := html.Parse(strings.NewReader(rawContent))
	if err != nil {
		logger.Errorf(ctx, "contentFilterScripts err:%v", err)
		return ""
	}

	// 移除<script>标签
	for round := strings.Count(rawContent, "<script"); round > 0; round-- {
		removeScripts(doc)
	}

	// 将修改后的HTML文档转换回字符串
	var result strings.Builder
	err = html.Render(&result, doc)
	if err != nil {
		logger.Errorf(ctx, "contentFilterScripts err:%v", err)
		return ""
	}

	// 输出清洗后的HTML
	return result.String()
}
