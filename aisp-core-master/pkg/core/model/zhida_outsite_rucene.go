package model

var ZhidaOutSitePath = "/rucene/ai/zhidaoutsite"
var ZhidaOutSiteIndex = "batch_zhidaoutsite_202406061616"

var ZhidaOutSiteMapping = map[string]map[string]any{
	"content": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"content_seg": {
		"type":          "segmented",
		"index_options": "docs",
		"index":         true,
		"similarity":    "BM25-0_75-1_2",
	},
	"domain": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_keyword1": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_long1": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
	"id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"biz_type": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"link_url": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"publish_time_second": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
	"source": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"source_type": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"title": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"upsert_time_second": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
}

var ZhidaOutSiteSetting = map[string]any{
	"index.provided_name": "code will override this",
	"similarities": map[string]any{
		"BM25-0_75-1_2": map[string]string{"b": "0.75",
			"k1":   "1.2",
			"type": "BM25",
		},
	},
}

type ZhidaOutSiteRucene struct {
	Id                string      `json:"id"`                  // 唯一id，生成方式为 url 的 hash
	Title             string      `json:"title"`               // 标题
	Content           string      `json:"content"`             // 正文
	ContentSeg        SegmentInfo `json:"content_seg"`         // 正文切词结果
	Domain            string      `json:"domain"`              // 领域
	BizType           string      `json:"biz_type"`            // 业务类型，例如热点
	LinkUrl           string      `json:"link_url"`            // 网站 url 地址
	Source            string      `json:"source"`              // 来源
	SourceType        string      `json:"source_type"`         // 来源类型
	PublishTimeSecond int64       `json:"publish_time_second"` // 内容发布时间，秒级
	UpsertTimeSecond  int64       `json:"upsert_time_second"`  // 内容发布时间，秒级
}
