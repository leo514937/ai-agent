package model

var AIDailyMappings = map[string]map[string]any{
	"answer_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"doc_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"parent_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"question_title": {
		"type":       "segmented",
		"similarity": "BM25-0_75-1_2",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
	"theme": {
		"type":       "segmented",
		"similarity": "BM25-0_75-1_2",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
	"summary": {
		"type":       "segmented",
		"similarity": "BM25-0_75-1_2",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
	"ques_summary": {
		"type":       "segmented",
		"similarity": "BM25-0_75-1_2",
		"fields": map[string]map[string]any{
			"raw": {
				"type":  "text",
				"store": true,
			},
		},
	},
	"author_id": {
		"type":          "keyword",
		"index_options": "docs",
		"index":         true,
	},
	"create_time": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
	"share_time": {
		"type":          "long",
		"index_options": "docs",
		"index":         true,
	},
}

var AIDailySettings = map[string]any{
	"index.provided_name":      "batch_aidaily_20250424",
	"index.compatible_version": "1",
	"index.sort.field":         "create_time",
	"index.sort.order":         "desc",
	"similarities": map[string]any{
		"BM25-0_75-1_2": map[string]string{
			"b":    "0.75",
			"k1":   "1.2",
			"type": "BM25",
		},
	},
}
