package conf

const (
	RucenePath  = "/rucene/ai/aidaily"
	RuceneIndex = "batch_aidaily_20250425"
)

const (
	RuceneBatchSize  = 3 // 写rucene的批量数
	SegmentBatchSize = 3 // 分词的批量数
)

const (
	RuceneDocTypeAnswer   = "answer"
	RuceneDocTypeQuestion = "question"
)

const (
	RuceneFieldAnswerID      = "answer_id"
	RuceneFieldDocID         = "doc_id"
	RuceneFieldParentID      = "parent_id"
	RuceneFieldQuestionTitle = "question_title"
	RuceneFieldTheme         = "theme"
	RuceneFieldSummary       = "summary"
	RuceneFieldQuesSummary   = "ques_summary"
	RuceneFieldAuthorID      = "author_id"
	RuceneFieldCreateTime    = "create_time"
	RuceneFieldShareTime     = "share_time"
)
