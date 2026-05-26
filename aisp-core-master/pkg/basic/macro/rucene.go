package macro

const (
	KnowledgeBasedRucenePath  = "/rucene/community/aisp"
	KnowledgeBasedRuceneIndex = "batch_knowledgebase_20230918"
)

const (
	RuceneFieldDocID       = "doc_id"      // db 中的 id
	RuceneFieldDescription = "description" // 图片描述
	RuceneFieldName        = "name"        // 知识库名称
	RuceneFieldImageToken  = "image_token" // 图片 token
	RuceneFieldTags        = "tags"        // 标签
	RuceneFieldState       = "state"       // 状态， available 可用， unavailable 不可用
	RuceneFieldCreatedAt   = "created_at"
)

var KnowledgeBasedStoreFields = []string{
	RuceneFieldName,
	RuceneFieldDescription,
	RuceneFieldTags,
	RuceneFieldImageToken,
	RuceneFieldState,
}

// 数字分身 field
const (
	RuceneFieldId             = "id"
	RuceneFieldEnable         = "enable"
	RuceneFieldContent        = "content"
	RuceneFieldTitle          = "title"
	RuceneFieldAuthorId       = "author_id"
	RuceneFieldContentSeg     = "content_seg"
	RuceneFieldBayesFirstName = "bayes_first_name"
	RuceneFieldDocIdCopy      = "doc_id_copy"
	RuceneFieldDocType        = "doc_type"
)

// 数字分身 rucene 地址
const (
	DigitalAuthorCustomRucenePath  = "/rucene/ai/digitaluserupload"
	DigitalAuthorCustomRuceneIndex = "batch_digitaluserupload_20240201"
	DigitalAuthorLawRucenePath     = "/rucene/ai/lawcodefine"
	DigitalAuthorLawRuceneIndex    = "202401311900"
)

var DigitalAuthorStoreFields = []string{
	RuceneFieldId,
	RuceneFieldEnable,
	RuceneFieldTitle,
	RuceneFieldContent,
	RuceneFieldAuthorId,
	RuceneFieldBayesFirstName,
	RuceneFieldDocIdCopy,
	RuceneFieldDocType,
}

const (
	AvailableState   = "available"
	UnavailableState = "unavailable"
)

// tracing日志 field

var LogTracingStoreFields = []string{
	TracingFieldMemberId,
	TracingFieldSessionId,
	TracingFieldScene,
	TracingFieldTrafficSource,
	TracingFieldMessageId,
	TracingFieldQuery,
	TracingFieldRequestTimeMs,
	TracingFieldResponseTimeMs,
	TracingFieldRespMessageId,
	TracingFieldResponse,
	TracingFieldSecurity,
	TracingFieldTraceId,
	TracingFieldGraphName,
	TracingFieldRequestInfo,
	TracingFieldResponseInfo,
	TracingFieldAppName,
	TracingFieldServiceName,
}

const (
	TracingFieldId             = "id"
	TracingFieldMemberId       = "member_id"
	TracingFieldScene          = "scene"
	TracingFieldTrafficSource  = "traffic_source"
	TracingFieldRequestTimeMs  = "request_time_ms"
	TracingFieldResponseTimeMs = "response_time_ms"
	TracingFieldMessageId      = "message_id"
	TracingFieldRespMessageId  = "resp_message_id"
	TracingFieldSessionId      = "session_id"
	TracingFieldQuery          = "query"
	TracingFieldQuerySeg       = "query_seg"
	TracingFieldResponseSeg    = "response_seg"
	TracingFieldResponse       = "response"
	TracingFieldSecurity       = "security"
	TracingFieldTraceId        = "trace_id"
	TracingFieldGraphName      = "graph_name"
	TracingFieldRequestInfo    = "request_info"
	TracingFieldResponseInfo   = "response_info"
	TracingFieldAppName        = "app_name"
	TracingFieldServiceName    = "service_name"
)

const (
	ZhidaId                = "id"
	ZhidaTitle             = "title"
	ZhidaContent           = "content"
	ZhidaDomain            = "domain"
	ZhidaBizType           = "biz_type"
	ZhidaLinkUrl           = "link_url"
	ZhidaSource            = "source"
	ZhidaSourceType        = "source_type"
	ZhidaPublishTimeSecond = "publish_time_second"
)

const (
	ScienceDocId   = "doc_id"
	ScienceUrl     = "url"
	ScienceTitle   = "title"
	ScienceContent = "content"
)

const (
	PersonalKnowledgeBaseContentFieldName           = "content"
	PersonalKnowledgeBaseTitleFieldName             = "title"
	PersonalKnowledgeBaseAbstractFieldName          = "abstract"
	PersonalKnowledgeBaseTagsRuceneFieldName        = "extra_field1"
	PersonalKnowledgeBaseDescriptionRuceneFieldName = "extra_field1"
)

var PersonalKnowledgeBaseDocStoreFields = []string{
	PersonalKnowledgeBaseMemberIdFieldName,
	PersonalKnowledgeBaseDocIdFieldName,
	PersonalKnowledgeBaseDocTypeFieldName,
	PersonalKnowledgeBaseKnowledgeBaseIdFieldName,
	PersonalKnowledgeBaseKnowledgeBaseTypeFieldName,
	PersonalKnowledgeBaseTitleFieldName,
	PersonalKnowledgeBaseAbstractFieldName,
}

var PersonalKnowledgeBaseStoreFields = []string{
	PersonalKnowledgeBaseMemberIdFieldName,
	PersonalKnowledgeBaseKnowledgeBaseIdFieldName,
	PersonalKnowledgeBaseKnowledgeBaseTypeFieldName,
	PersonalKnowledgeBaseKnowledgeBaseNameFieldName,
}

var PublicKnowledgeBaseStoreFields = []string{
	PersonalKnowledgeBaseMemberIdFieldName,
	PersonalKnowledgeBaseKnowledgeBaseIdFieldName,
	PersonalKnowledgeBaseKnowledgeBaseTypeFieldName,
	PersonalKnowledgeBaseKnowledgeBaseNameFieldName,
	PersonalKnowledgeBaseKnowledgeBaseDescriptionFieldName,
	PersonalKnowledgeBaseKnowledgeBaseVisibilityFieldName,
}
