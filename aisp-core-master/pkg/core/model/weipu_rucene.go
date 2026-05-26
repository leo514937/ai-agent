package model

var WeiPuPath = "/rucene/ai/weipu"
var WeiPuIndex = "batch_weipu_202407251430"

var WeiPuMapping = map[string]map[string]any{
	"content": {
		"type": "keyword",
	},
	"content_seg": {
		"type":          "segmented",
		"index_options": "docs",
		"index":         true,
		"similarity":    "BM25-0_75-1_2",
	},
	"doc_id": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
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
	"source": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
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

var WeiPuSetting = map[string]any{
	"index.provided_name": "code will override this",
	"similarities": map[string]any{
		"BM25-0_75-1_2": map[string]string{"b": "0.75",
			"k1":   "1.2",
			"type": "BM25",
		},
	},
}

type WeiPuRucene struct {
	Id          string      `json:"id"`           // 唯一id，生成方式为 title 的 hash
	Title       string      `json:"title"`        // 标题
	Url         string      `json:"url"`          // url，hash 后生成 id
	Content     string      `json:"content"`      // 正文
	ContentSeg  SegmentInfo `json:"content_seg"`  // 正文切词结果
	DocId       int64       `json:"doc_id"`       // doc_id, 目前没有
	PublishTime string      `json:"publish_time"` // 期刊发布时间，格式例如：2021年02期
	PublishYear int32       `json:"publish_year"` // 期刊发布年份，格式例如：2021
	Source      string      `json:"source"`       // 来源，例如：证券市场红周刊
}
