package model

var PersonalKnowledgeDocBackUpPath = "/rucene/ai/personalkbdoc"
var PersonalKnowledgeDocBackUpIndex = "batch_personalkbdoc_202501161525"

var PersonalKnowledgeDocPath = "/rucene/ai/personalkbdocv2"
var PersonalKnowledgeDocIndex = "batch_personalkbdocv2_202506051451"

var InternalKnowledgeDocPath = "/rucene/ai/internalkbdoc"
var InternalKnowledgeDocIndex = "batch_internalkbdoc_202503311642"

var PersonalKnowledgeDocMapping = map[string]map[string]any{
	"id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"member_id": {
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
	"knowledge_base_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"knowledge_base_type": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"knowledge_base_name": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"visibility": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_field1": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_field2": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_field3": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"extra_field4": {
		"type":          "long",
		"index_options": "docs",
	},
	"extra_field5": {
		"type":          "long",
		"index_options": "docs",
	},
	"extra_field6": {
		"type":          "long",
		"index_options": "docs",
	},
	"content": {
		"type":        "segmented",
		"similarity":  "BM25-0_75-1_2",
		"term_vector": "with_positions_offsets",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
	"title": {
		"type":        "segmented",
		"similarity":  "BM25-0_75-1_2",
		"term_vector": "with_positions_offsets",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
	"abstract": {
		"type":        "segmented",
		"similarity":  "BM25-0_75-1_2",
		"term_vector": "with_positions_offsets",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
	"extra_seg1": {
		"type":        "segmented",
		"similarity":  "BM25-0_75-1_2",
		"term_vector": "with_positions_offsets",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
	"extra_seg2": {
		"type":        "segmented",
		"similarity":  "BM25-0_75-1_2",
		"term_vector": "with_positions_offsets",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
	"extra_seg3": {
		"type":        "segmented",
		"similarity":  "BM25-0_75-1_2",
		"term_vector": "with_positions_offsets",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
}

var PersonalKnowledgeDocSetting = map[string]any{
	"index.provided_name": "code will override this",
	"similarities": map[string]any{
		"BM25-0_75-1_2": map[string]string{"b": "0.75",
			"k1":   "1.2",
			"type": "BM25",
		},
	},
}

type PersonalKnowledgeDocRucene struct {
	Id                string      `json:"id"`                  // 唯一id，生成方式为 hash
	MemberId          int64       `json:"member_id"`           // 用户id
	DocId             int64       `json:"content_id"`          // 文档id
	DocType           string      `json:"doc_type"`            // 文档类型
	KnowledgeBaseId   int64       `json:"knowledge_base_id"`   // 知识库id
	KnowledgeBaseType string      `json:"knowledge_base_type"` // 知识库类型
	KnowledgeBaseName string      `json:"knowledge_base_name"` // 知识库名称
	Visibility        string      `json:"visibility"`          // 可见性
	Tags              []string    `json:"extra_field1"`        // 标签
	Content           SegmentInfo `json:"content"`             // 内容
	Title             SegmentInfo `json:"title"`               // 标题
	Abstract          SegmentInfo `json:"abstract"`            // 摘要
}
