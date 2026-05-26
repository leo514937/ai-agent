package model

var ArxivPath = "/rucene/ai/arxiv"
var ArxivIndex = "batch_arxiv_202408161937"

var ArxivMapping = map[string]map[string]any{
	"content": {
		"type": "keyword",
	},
	"content_seg": {
		"type":          "segmented",
		"index_options": "docs",
		"index":         true,
		"similarity":    "BM25-0_75-1_2",
	},
	"id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"publish_time": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"publish_year": {
		"type":          "integer",
		"index_options": "docs",
		"index":         true,
	},
	"author": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"subject": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"abstract": {
		"type":          "keyword",
		"index_options": "docs",
	},
	"title": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"url": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
}

var ArxivSetting = map[string]any{
	"index.provided_name": "code will override this",
	"similarities": map[string]any{
		"BM25-0_75-1_2": map[string]string{"b": "0.75",
			"k1":   "1.2",
			"type": "BM25",
		},
	},
}

type ArxivRucene struct {
	Id          string      `json:"id"`           // 唯一id，生成方式为 title 的 hash
	Title       string      `json:"title"`        // 标题
	Url         string      `json:"url"`          // url，hash 后生成 id
	Content     string      `json:"content"`      // 正文
	ContentSeg  SegmentInfo `json:"content_seg"`  // 正文切词结果
	PublishTime string      `json:"publish_time"` // 期刊发布时间，格式例如：2021年02期
	Author      []string    `json:"author"`       // 来源，例如：证券市场红周刊
	Subject     string      `json:"subject"`      // 学科分类
	Abstract    string      `json:"abstract"`     // 摘要
}
