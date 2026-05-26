package module

import proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"

type PrefabWordKafkaMsg struct {
	QuestionContent string   `json:"question_content"` // 问题内容 鸟有嗅觉吗？
	GoodDocIds      []int64  `json:"good_doc_ids"`     // 文章ID 123213,123213
	GoodDocTypes    []string `json:"good_doc_types"`   // 文章类型 ANSWER, ARTICLE
	SourceChannel   string   `json:"source_channel"`   // 消息源 站外热点 站内热点 优质
	AiAnswer        string   `json:"ai_answer"`        // AI回答 鸟类......
	AiQuestion      string   `json:"ai_question"`      // AI问题 鸟类是如何利用嗅觉寻找实物的？
}

func (p *PrefabWordKafkaMsg) GetQueryType() proto.QueryType {
	// source_channel 区分优质就行，不是优质都算作热点的类型
	switch p.SourceChannel {
	case "优质":
		return proto.QueryType_PREFAB_WORD_QUESTION
	default:
		return proto.QueryType_PREFAB_WORD_HOT_QUESTION
	}
}
