package model

var PersonalKnowledgeBasePath = "/rucene/ai/personalkb"
var PersonalKnowledgeBaseIndex = "batch_personalkb_202412271515"

var PersonalKnowledgeBaseMapping = map[string]map[string]any{
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

var PersonalKnowledgeBaseSetting = map[string]any{
	"index.provided_name": "code will override this",
	"similarities": map[string]any{
		"BM25-0_75-1_2": map[string]string{"b": "0.75",
			"k1":   "1.2",
			"type": "BM25",
		},
	},
}

type PersonalKnowledgeBaseRucene struct {
	Id                string      `json:"id"`                  // 唯一id，生成方式为 hash
	MemberId          int64       `json:"member_id"`           // 用户id
	KnowledgeBaseId   int64       `json:"knowledge_base_id"`   // 知识库id
	KnowledgeBaseType string      `json:"knowledge_base_type"` // 知识库类型
	KnowledgeBaseName SegmentInfo `json:"knowledge_base_name"` // 知识库名称
}
