package model

var CrawlerWebpagePath = "/rucene/ai/crawlerwebpage"
var CrawlerWebpageIndex = "batch_crawlerwebpage_202502281748"

var CrawlerWebpageMapping = map[string]map[string]any{
	"id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"content_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"doc_type": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"domain": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"sparse_score": {
		"index_options": "positions",
		"type":          "keyword",
		"index":         true,
	},
}

var CrawlerWebpageSetting = map[string]any{
	"index.provided_name": "code will override this",
	"similarities": map[string]any{
		"BM25-0_75-1_2": map[string]string{"b": "0.75",
			"k1":   "1.2",
			"type": "BM25",
		},
	},
}

type CrawlerWebpageRucene struct {
	Id          string        `json:"id"`           // 唯一id，生成方式为 hash
	DocId       int64         `json:"content_id"`   // 文档id
	DocType     string        `json:"doc_type"`     // 文档类型
	Domain      string        `json:"domain"`       // 域名
	Extra       string        `json:"extra"`        // 额外信息
	SparseScore []*SparseWord `json:"sparse_score"` // 切词内容
}
