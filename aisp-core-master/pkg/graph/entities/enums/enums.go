package enums

// CorrelationType 相关性类型
type CorrelationType string

func (c CorrelationType) String() string {
	return string(c)
}

const (
	// Correlation 相关
	Correlation CorrelationType = "Correlation"
	// UnCorrelation 不相关
	UnCorrelation CorrelationType = "UnCorrelation"
)

// TimelinessType 时效类型
type TimelinessType string

func (c TimelinessType) String() string {
	return string(c)
}

const (
	// TimelinessByNone 无时效
	TimelinessByNone TimelinessType = "none"
	// TimelinessByShort 短时效
	TimelinessByShort TimelinessType = "short"
	// TimelinessByIntermediate 中时效
	TimelinessByIntermediate TimelinessType = "intermediate"
)

// TimelinessResStatusType 时效结果状态
type TimelinessResStatusType string

func (c TimelinessResStatusType) String() string {
	return string(c)
}

const (
	// TimelinessResByNormal 正常
	TimelinessResByNormal TimelinessResStatusType = "normal"
	// TimelinessResByHallucination 幻觉
	TimelinessResByHallucination TimelinessResStatusType = "hallucination"
)

const (
	PromptElementKnowledgeContext         = "knowledge_context"
	PromptElementContextAssistantResponse = "context_assistant_response"
	PromptElementQuery                    = "query"
	PromptElementChatHistory              = "chat_history"
)

// ChatSchema 对话模式
type ChatSchema string

func (c ChatSchema) String() string {
	return string(c)
}

const (
	// ChatSchemaByNormal 正常
	ChatSchemaByNormal ChatSchema = "normal"
	// ChatSchemaByUpdateTitle 修改标题
	ChatSchemaByUpdateTitle ChatSchema = "update_title"
	// ChatSchemaByReAnswer 重答
	ChatSchemaByReAnswer ChatSchema = "re_answer"
	// ChatSchemaByReAnswerV2 重答V2
	ChatSchemaByReAnswerV2 ChatSchema = "re_answer_v2"
)

// SimilarTextType 内容相关性类型
type SimilarTextType string

func (c SimilarTextType) String() string {
	return string(c)
}

const (
	// SimilarTextTypeByTitle 标题
	SimilarTextTypeByTitle SimilarTextType = "title"
	// SimilarTextTypeByTitleAndContent2048 标题和内容2048
	SimilarTextTypeByTitleAndContent2048 SimilarTextType = "title+content2048"
	// SimilarTextTypeByTitleAndAbstract 标题和摘要
	SimilarTextTypeByTitleAndAbstract SimilarTextType = "title+abstract"
	// SimilarTextTypeByContent2048 内容正文2048
	SimilarTextTypeByContent2048 SimilarTextType = "content2048"
)

// ZhiDaProSourceType 专业版直答 数据源类型
type ZhiDaProSourceType string

func (c ZhiDaProSourceType) String() string {
	return string(c)
}

const (
	// ZhiDaProSourceByPublic 公共知识库
	ZhiDaProSourceByPublic ZhiDaProSourceType = "public"
	// ZhiDaProSourceByPersonal 个人知识库
	ZhiDaProSourceByPersonal ZhiDaProSourceType = "personal"
	// ZhiDaProSourceByUserSpecifiedDoc 指定文档
	ZhiDaProSourceByUserSpecifiedDoc ZhiDaProSourceType = "specified_doc"
	// ZhiDaProSourceByUserPublicAndPersonal 公共知识库与个人知识库混合
	ZhiDaProSourceByUserPublicAndPersonal ZhiDaProSourceType = "public_and_personal"
)
