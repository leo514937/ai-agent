package model

import (
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhsearch/rucenego/v2/client"
)

type KnowledgeModel struct {
	Description string   `json:"description"`
	Name        string   `json:"name"`
	Tags        []string `json:"tags"`
	ImageToken  string   `json:"image_token"`
}

type RuceneSearchRequest struct {
	RucenePath  string       `json:"rucene_path"`
	Index       string       `json:"index"`
	QueryFields []string     `json:"query_fields"`
	QueryDef    client.Query `json:"query_def"`
	Offset      int          `json:"offset"`
	Limit       int          `json:"limit"`
}

type RuceneSearchResult struct {
	Total int64             `json:"total"`
	List  []*KnowledgeModel `json:"list"`
}

type KnowledgeBaseState int

const (
	// KnowledgeBaseStateInit 初始状态
	KnowledgeBaseStateInit KnowledgeBaseState = 0
	// KnowledgeBaseStateDeleted 已删除
	KnowledgeBaseStateDeleted KnowledgeBaseState = -1
)

type KnowledgeBaseDocState int

const (
	// KnowledgeBaseDocStateInit 初始状态
	KnowledgeBaseDocStateInit KnowledgeBaseDocState = 0
	// KnowledgeBaseDocStateParsed 被解析完成
	KnowledgeBaseDocStateParsed KnowledgeBaseDocState = 1
	// KnowledgeBaseDocStateParseError 文档解析错误
	KnowledgeBaseDocStateParseError KnowledgeBaseDocState = 2
	// KnowledgeBaseDocStateDeleted 已删除
	KnowledgeBaseDocStateDeleted KnowledgeBaseDocState = 3
)

type KnowledgeBaseDocSourceType int

const (
	KnowledgeBaseDocSourcePdf        KnowledgeBaseDocSourceType = 1
	KnowledgeBaseDocSourceUrlZhihu   KnowledgeBaseDocSourceType = 2
	KnowledgeBaseDocSourceUrlOutSite KnowledgeBaseDocSourceType = 3
)

type KnowledgeBaseDoc struct {
	UniqueId         string                     `json:"unique_id" borm:"primary_key"`
	CreatorUserId    string                     `json:"creator_user_id"`
	KnowledgeBaseId  string                     `json:"knowledge_base_id"`
	DocName          string                     `json:"doc_name"`
	State            KnowledgeBaseDocState      `json:"state"`
	DocPath          string                     `json:"doc_path"`
	Url              string                     `json:"url" borm:"-"`
	DocSourceType    KnowledgeBaseDocSourceType `json:"doc_source_type"`
	ParsedAt         time.Time                  `json:"parsed_at"`
	ParseRuleVersion int64                      `json:"parse_rule_version"`
	CreatedAt        time.Time                  `json:"created_at" borm:"readonly"`
	UpdatedAt        time.Time                  `json:"updated_at" borm:"readonly"`
}

func (s *KnowledgeBaseDoc) TableName() string {
	return "knowledge_base_doc"
}

type KnowledgeBaseDocRaw struct {
	FileContent []byte                     `json:"-"`
	FileName    string                     `json:"file_name"`
	Path        string                     `json:"-"`
	FileUrl     string                     `json:"file_url"`
	UniqueId    string                     `json:"unique_id"`
	DocType     KnowledgeBaseDocSourceType `json:"doc_type"`
	Text        string                     `json:"text"`
}

type KnowledgeBaseDocParseTask struct {
	KnowledgeBaseDocId string
	DocContent         []byte
}

type KnowledgeBaseRetrieveResult struct {
	Text       string  `json:"text"`
	Similarity float32 `json:"similarity"`
}

type KnowledgeBaseChunk struct {
	Id               int64 `borm:"primary_key"`
	ChunkText        string
	DocId            string
	ParseRuleVersion int64
	CreatedAt        time.Time `borm:"readonly"`
}

// ------------------ 公司内部知识库 ------------------

type KnowledgeBase struct {
	UniqueId          string                          `json:"unique_id"  borm:"primary_key"`
	KnowledgeBaseType proto.PersonalKnowledgeBaseType `json:"knowledge_base_type"`
	KnowledgeBaseName string                          `json:"knowledge_base_name"`
	CreatorUserId     string                          `json:"creator_user_id"`
	State             KnowledgeBaseState              `json:"state"`
	BizGroup          string                          `json:"biz_group"`
	KnowledgeBasePath string                          `json:"knowledge_base_path"` // deprecated
	Docs              []*KnowledgeBaseDoc             `json:"docs" borm:"-"`       // deprecated
	CreatedAt         time.Time                       `json:"created_at" borm:"readonly"`
	UpdatedAt         time.Time                       `json:"updated_at" borm:"readonly"`
}

type DocSubtype string

const (
	DocSubtypePdf      DocSubtype = "pdf"
	DocSubtypeMarkdown DocSubtype = "markdown"
	DocSubtypeText     DocSubtype = "text"
)

type DocumentInfo struct {
	Id              int64      `json:"id" borm:"primary_key"`
	DocId           int64      `json:"doc_id"`
	DocType         string     `json:"doc_type"`
	DocSubtype      DocSubtype `json:"doc_subtype"`
	Title           string     `json:"title"`
	Abstract        string     `json:"abstract"`
	Content         string     `json:"content"`
	LastUpdatedTime int64      `json:"last_updated_time"`
	Url             string     `json:"url"`
	OssPath         string     `json:"oss_path"`
	Tags            string     `json:"tags"`
	AuthorityLevel  string     `json:"authority_level"`
	DocSource       string     `json:"doc_source"`
	BizGroup        string     `json:"biz_group"`
	Operator        string     `json:"operator"`
	CreatedAt       time.Time  `json:"created_at" borm:"readonly"`
	UpdatedAt       time.Time  `json:"updated_at" borm:"readonly"`
}

func (d *DocumentInfo) FillDocSubtype() {
	if strings.HasSuffix(d.Title, ".pdf") {
		d.DocSubtype = DocSubtypePdf
	} else if strings.HasSuffix(d.Title, ".md") {
		d.DocSubtype = DocSubtypeMarkdown
	} else if strings.HasSuffix(d.Title, ".txt") {
		d.DocSubtype = DocSubtypeText
	}
}

type KnowledgeBaseDocV2 struct {
	Id                int64                           `json:"id" borm:"primary_key"`
	KnowledgeBaseId   int64                           `json:"knowledge_base_id"`
	KnowledgeBaseType proto.PersonalKnowledgeBaseType `json:"knowledge_base_type"`
	DocId             int64                           `json:"doc_id"`
	DocType           string                          `json:"doc_type"`
	Operator          string                          `json:"operator"`
	Visibility        proto.KnowledgeBaseVisibility   `json:"visibility"`
	CreatedAt         time.Time                       `json:"created_at" borm:"readonly"`
	UpdatedAt         time.Time                       `json:"updated_at" borm:"readonly"`
}
