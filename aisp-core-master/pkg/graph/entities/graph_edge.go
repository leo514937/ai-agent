package entities

const (
	Normal string = "normal"
	Break  string = "break"
)

const (
	NeedSummary string = "needSummary"
)

const (
	HasRetrieval   string = "hasRetrieval"
	EmptyRetrieval string = "emptyRetrieval"
)

const (
	HitCache  string = "hitCache"
	MissCache string = "missCache"
)

const (
	UploadRecallThenBreak = "uploadRecallThenBreak"
)

// DocRouter 文档路由
type DocRouter string

func (d DocRouter) String() string {
	return string(d)
}

const (
	KnowledgeBase   DocRouter = "knowledgeBase"
	SpecifiedDocAny DocRouter = "specifiedDocAny"
	//SpecifiedDocEach DocRouter = "specifiedDocEach"
	//SpecifiedDocTranslation DocRouter = "specifiedDocTranslation"
	// 后期可以增加组合模式
	// KnowledgeBase + SpecifiedDocAny
	// KnowledgeBase + SpecifiedDocEach
)
