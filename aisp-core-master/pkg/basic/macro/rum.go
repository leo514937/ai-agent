package macro

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"github.com/pkg/errors"
)

// 数字分身 rum 索引表名
const (
	ZhihuIndexRumTable   = "digital_user_pt_moco_64d"     // 知乎站内内容索引
	AuthorCustomRumTable = "digital_user_pt_custom_1024d" // 用户主动编辑上传内容索引
	LawRumTable          = "digital_user_pt_law_1024d"    // 法条索引
)

// 直达站外内容 rum 索引表名
const ZhidaOutSiteRumTable = "zhida_outsite_bge_emb_1024d"

// 创作者的索引
const ZhidaAuthorBgeRumTable = "ai_zhida_author_bge_1024d"

// 直达站外内容 rum 索引表名
const ZPlusAutomotiveRumTable = "rum_brand_zhi_pt_1024d"

// 龙源数据 rum 索引表名
const LongYuanTitleAndContentRumTable = "longyuan_bge_emb_1024d"
const LongYuanTitleRumTable = "longyuan_title_bge_emb_1024d"
const LongYuanContentRumTable = "longyuan_content_bge_emb_1024d"

// 维普数据 rum 索引表名
const WeiPuTitleAndContentRumTable = "weipu_bge_emb_1024d"
const WeiPuTitleRumTable = "weipu_title_bge_emb_1024d"
const WeiPuContentRumTable = "weipu_content_bge_emb_1024d"

// 维基中文 rum 索引表名
const WikiZhTitleAndContentRumTable = "wiki_zh_bge_emb_1024d"
const WikiZhTitleRumTable = "wiki_zh_title_bge_emb_1024d"
const WikiZhContentRumTable = "wiki_zh_content_bge_emb_1024d"

// 维基英文 rum 索引表名
const WikiEnTitleAndContentRumTable = "wiki_en_bge_emb_1024d"
const WikiEnTitleRumTable = "wiki_en_title_bge_emb_1024d"
const WikiEnContentRumTable = "wiki_en_content_bge_emb_1024d"

// 个人知识库 rum 索引表名
const PersonalKnowledgeBaseTitleRumTable = "personal_kb_title_1024d"
const PersonalKnowledgeBaseQuestionRumTable = "personal_kb_question_1024d"
const PersonalKnowledgeBaseContentRumTable = "personal_kb_content_1024d"

// 内部知识库 rum 索引表名
const InternalKnowledgeBaseTitleRumTable = "internal_kb_title_1024d"
const InternalKnowledgeBaseQuestionRumTable = "internal_kb_question_1024d"

const CrawlerWebpageTitleRumTable = "crawler_webpage_title_1024d" // 一期不用
const CrawlerWebpageContentRumTable = "crawler_webpage_content_1024d"

// rum field 名
const (
	IdFieldName              = "id"
	AuthorIdFieldName        = "author_id"
	DocIdCopyFieldName       = "doc_id_copy"
	DocTypeFieldName         = "doc_type"
	DocUrlFieldName          = "doc_url"
	TitleFieldName           = "title"
	ContentFieldName         = "content"
	ContentLevelFieldName    = "content_level"
	BayesFirstNameFieldName  = "bayes_first_name"
	EnableFieldName          = "enable"
	EmbeddingSourceFieldName = "embedding_source"
)

var DigitalAuthorFields = []string{
	IdFieldName,
	AuthorIdFieldName,
	DocIdCopyFieldName,
	DocTypeFieldName,
	DocUrlFieldName,
	TitleFieldName,
	ContentFieldName,
	ContentLevelFieldName,
	BayesFirstNameFieldName,
	EnableFieldName,
	EmbeddingSourceFieldName,
}

// Ai Tab 引导词 rum 索引表名
const (
	QuestionRewriteForRecRumTable = "vi2402292138300002_1024d"
	QuestionRewriteForHotRumTable = "vi2402292135500001_1024d"
	AiPrefabWordRumTable          = "ai_prefab_word_1024d"
	AiPrefabWordV2RumTable        = "ai_prefab_word_v2_1024d"
	AiPrefabWordV3RumTable        = "ai_prefab_word_v3_1024d"
)

// PrefabQueryType2RumTableName prefab query type 转 rum table name
func PrefabQueryType2RumTableName(queryType proto.QueryType) (string, error) {
	switch queryType {
	case proto.QueryType_PREFAB_WORD_QUESTION:
		return QuestionRewriteForRecRumTable, nil
	case proto.QueryType_PREFAB_WORD_HOT_QUESTION:
		return QuestionRewriteForHotRumTable, nil
	default:
		return "", errors.Errorf("invalid queryType: %v", queryType.String())
	}
}

// Ai Tab 引导词 rum field 名
const (
	QuestionRewriteIdFieldName        = "id"
	QuestionRewriteHashFieldName      = "hash"
	QuestionRewriteStatusFieldName    = "status"
	QuestionRewriteRawFieldName       = "raw"
	QuestionRewriteCreatedAtFieldName = "created_at"
	QuestionRewriteUpdatedAtFieldName = "updated_at"
)

// 直达站外索引 rum field 名
const (
	ZhidaOutSiteIdFieldName             = "id"
	ZhidaOutSiteTitleFieldName          = "title"
	ZhidaOutSiteContentFieldName        = "content"
	ZhidaOutSiteLinkUrlFieldName        = "link_url"
	ZhidaOutSiteLinkSourceFieldName     = "source"
	ZhidaOutSiteLinkSourceTypeFieldName = "source_type"
	ZhidaOutSiteBizTypeFieldName        = "biz_type"
	ZhidaOutSiteDomainFieldName         = "domain"
	ZhidaOutSitePublishTimeFieldName    = "publish_time"
	ZhidaOutSiteEmbeddingFieldName      = "embedding"
)

var ZhidaOutSiteBizTypeFields = []string{
	ZhidaOutSiteIdFieldName,
	ZhidaOutSiteTitleFieldName,
	ZhidaOutSiteContentFieldName,
	ZhidaOutSiteLinkUrlFieldName,
	ZhidaOutSiteLinkSourceFieldName,
	ZhidaOutSiteLinkSourceTypeFieldName,
	ZhidaOutSiteBizTypeFieldName,
	ZhidaOutSiteDomainFieldName,
	ZhidaOutSitePublishTimeFieldName,
	ZhidaOutSiteEmbeddingFieldName,
}

// 个人知识库索引 rum field 名
const (
	PersonalKnowledgeBaseIdFieldName                       = "id"
	PersonalKnowledgeBaseMemberIdFieldName                 = "member_id"
	PersonalKnowledgeBaseDocIdFieldName                    = "content_id"
	PersonalKnowledgeBaseDocTypeFieldName                  = "doc_type"
	PersonalKnowledgeBaseKnowledgeBaseIdFieldName          = "knowledge_base_id"
	PersonalKnowledgeBaseKnowledgeBaseTypeFieldName        = "knowledge_base_type"
	PersonalKnowledgeBaseKnowledgeBaseNameFieldName        = "knowledge_base_name"
	PersonalKnowledgeBaseKnowledgeBaseDescriptionFieldName = "knowledge_base_desc"
	PersonalKnowledgeBaseKnowledgeBaseVisibilityFieldName  = "knowledge_base_visibility" // base 索引
	PersonalKnowledgeBaseVisibilityFieldName               = "visibility"                // doc 索引
	PersonalKnowledgeBaseExtraRumFieldName                 = "extra"
	PersonalKnowledgeBaseExtra2RumFieldName                = "extra2"
	PersonalKnowledgeRawFieldName                          = "raw"
)

// 创作者 rum field 名
const (
	ZhidaAuthorFiledNameId         = "id"
	ZhidaAuthorFiledNameSimilarity = "sim"
	ZhidaAuthorFiledNameAuthorId   = "author_id"
	ZhidaAuthorFiledNameRaw        = "raw"
)

var ZhidaAuthorFields = []string{
	ZhidaAuthorFiledNameAuthorId,
	ZhidaAuthorFiledNameRaw,
}

// 学术索引 rum field 名
const (
	ScienceKBIdFieldName      = "id"
	ScienceKBFieldName        = "title"
	ScienceKBRawFieldName     = "raw"
	ScienceKBContentFieldName = "content"
	ScienceKBUrlFieldName     = "url"
	ScienceKBDocIdFieldName   = "doc_id"
	ScienceKBSourceFieldName  = "source"
	ScienceKBPublishFieldName = "publish_time"
)

var ScienceBizTypeFields = []string{
	ScienceKBFieldName,
	ScienceKBRawFieldName,
	ScienceKBUrlFieldName,
	ScienceKBDocIdFieldName,
	ScienceKBSourceFieldName,
	ScienceKBPublishFieldName,
}

// 引导词 rum field 名
const (
	PrefabWordQueryTypeFieldName = "query_type"
	PrefabWordRawFieldName       = "raw"
)

var PrefabWordFields = []string{
	PrefabWordQueryTypeFieldName,
	PrefabWordRawFieldName,
}

const (
	KnowledgeBaseDocContent       = "raw"
	KnowledgeBaseDocUniqueId      = "doc_unique_id"
	KnowledgeBaseDocCreatorUserId = "creator_user_id"
)

var KnowledgeBaseDocFields = []string{
	KnowledgeBaseDocContent,
	KnowledgeBaseDocUniqueId,
	KnowledgeBaseDocCreatorUserId,
}

// 直达站外索引 rum field 名
const (
	CrawlerWebpageIdFieldName      = "id"
	CrawlerWebpageDocIdFieldName   = "content_id"
	CrawlerWebpageDocTypeFieldName = "doc_type"
	CrawlerWebpageDomainFieldName  = "domain"
	CrawlerWebpageExtraFieldName   = "extra"
)

var CrawlerWebpageFields = []string{
	CrawlerWebpageDocIdFieldName,
	CrawlerWebpageDocTypeFieldName,
	CrawlerWebpageDomainFieldName,
	CrawlerWebpageExtraFieldName,
}
