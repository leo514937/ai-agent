package macro

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
)

const (
	// CensorOperationRemove 审核结果删除
	CensorOperationRemove = "remove"
)

// CensorTypeMap 负反馈Map
var CensorTypeMap = map[proto.QueryType]string{
	// 未知、猜你想搜、段落词（老服务 AI词）
	proto.QueryType_QUERY_UNDEFINED: "paragraph_expansion_word",
	proto.QueryType_GUESS_WORD:      "paragraph_expansion_word",
	proto.QueryType_PARAGRAPH:       "paragraph_expansion_word",
	// 兴趣拓展词 (废弃)
	proto.QueryType_INTEREST_EXPANSION: "ai_interest_expansion_word",
	// AI 兴趣拓展词
	proto.QueryType_RELATE_WORD: "ai_tab_interest_expansion_word",
	// 新增 AI预制短语问题 AI相关短语问题
	proto.QueryType_PREFAB_WORD_QUESTION: "search_tab_prefab_word_question",
	proto.QueryType_RELATE_WORD_QUESTION: "search_tab_relate_word_question",
	// AI 预制短语问题(热榜)
	proto.QueryType_PREFAB_WORD_HOT_QUESTION: "search_tab_prefab_word_hot_question",
	// AI 预置词热点事件
	proto.QueryType_RELATE_WORD_HOT_EVENT: "search_tab_prefab_word_hot_event",
}

// CensorTypeAndWordTypeRef 审核Type 对照 本地wordType
var CensorTypeAndWordTypeRef = map[string]int32{
	// AI 兴趣拓展词
	"ai_tab_interest_expansion_word": int32(proto.QueryType_RELATE_WORD),
	// AI 预制短语问题
	"search_tab_prefab_word_question": int32(proto.QueryType_PREFAB_WORD_QUESTION),
	// AI 预制短语问题(热榜)
	"search_tab_prefab_word_hot_question": int32(proto.QueryType_PREFAB_WORD_HOT_QUESTION),
	// AI 相关短语问题
	"search_tab_relate_word_question": int32(proto.QueryType_RELATE_WORD_QUESTION),
	// AI 预置词热点事件
	"search_tab_prefab_word_hot_event": int32(proto.QueryType_RELATE_WORD_HOT_EVENT),
}
