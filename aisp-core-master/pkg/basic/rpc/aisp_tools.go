package rpc

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type ProcessorName string

func (p ProcessorName) String() string {
	return string(p)
}

const (
	ProcessorNameLlamaIndexPdfParser ProcessorName = "llama-index-pdf-parser"
	ProcessorNameTencentPdfParser    ProcessorName = "tencent-pdf-parser"
	ProcessorNameGeneralHtmlParser   ProcessorName = "general-html-parser"
	ProcessorNameZhihuHtmlParser     ProcessorName = "zhihu-html-parser"
	ProcessorNamePymuPdfParser       ProcessorName = "pymu-pdf-parser"
	ProcessorNameRulePdfParser       ProcessorName = "rule-pdf-parser"   // 简单版解析
	ProcessorNameVisionPdfParser     ProcessorName = "vision-pdf-parser" // 复杂版解析
	ProcessorNameLocalHtmlParser     ProcessorName = "local-html-parser" // 复杂版解析
)

type ProcessorType string

func (p ProcessorType) String() string {
	return string(p)
}

const (
	ProcessorTypePdfParser  ProcessorType = "pdf-parser"
	ProcessorTypeHtmlParser ProcessorType = "html-parser"
)

type AispToolsClient interface {
	ParsePdf(ctx context.Context, processorName ProcessorName, content []byte) ([]*model.AispToolsItem, error)
	ParseHtml(ctx context.Context, processorName ProcessorName, content []byte, description string, url string) ([]*model.AispToolsItem, error)
}
