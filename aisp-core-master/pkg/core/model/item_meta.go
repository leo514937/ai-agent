package model

import (
	"fmt"
	"sync"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/one-rpc-go/grpc-tag-core/tag_core"
	"git.in.zhihu.com/one-rpc-go/thrift-content_core/content_core_thrift/base"
	content2 "git.in.zhihu.com/one-rpc-go/thrift-content_prod/content_prod_thrift/content"
	query_profile "git.in.zhihu.com/pb-go/search-proto/query-profile"
	"git.in.zhihu.com/pb-go/zai-proto/ai/common"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/enums"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"github.com/samber/lo"
)

type ItemMeta struct {
	IndexDocUniqueId    int64                           `json:"index_doc_unique_id"`
	DocId               int64                           `json:"doc_id"`
	DocType             content.DocType_Type            `json:"doc_type"`
	AuthorId            int64                           `json:"author_id"`
	AuthorName          string                          `json:"author_name"`
	Title               string                          `json:"title"`
	Url                 string                          `json:"url"`
	UrlToken            string                          `json:"url_token"`
	Content             string                          `json:"content"`
	Raw                 string                          `json:"raw"` // 对于知乎站内内容，content为内容正文，raw为索引里的原始描述
	Abstract            string                          `json:"abstract"`
	OriginSnippet       string                          `json:"origin_snippet"` // 站外内容原始 snippet, 此处 abstract 是 snippet 截断的结果
	Domain              string                          `json:"domain"`
	SiteLevel           int                             `json:"site_level"`
	ContentLevel        int64                           `json:"content_level"`
	AuthorityLevel      proto.AuthorityLevel            `json:"authority_level"`
	BayesFirstName      string                          `json:"bayes_first_name"`
	RecallSourceInfo    *RecallSourceInfo               `json:"recall_source_info"`
	RankInfo            *RankInfo                       `json:"rank_info"`
	IntentionType       macro.IntentionType             `json:"intention_type"`
	BayesTagInfo        []*common.TagInfo               `json:"bayes_tag_info"`
	RequestThemeSimilar map[string]float64              `json:"request_theme_similar"`
	HitTaskId           int64                           `json:"hit_task_id"`
	QuKeywords          []*query_profile.QpTerm         `json:"qu_keywords"`
	KlaraEmbedding      []float32                       `json:"klara_embedding"`
	BgeM3Embedding      []float32                       `json:"bge_m3_embedding"`
	UnifiedEmbedding    []float32                       `json:"unified_embedding"`
	ContentInfo         *base.ContentInfo               `json:"content_info"`
	ParentContentInfo   *base.ContentInfo               `json:"parent_content_info"` // 父级内容，DocType 为 Answer 时此处为 Question
	ChildContentInfo    []*base.ContentInfo             `json:"child_content_info"`  // 子级内容，DocType 为 Question 时此处为 Answers
	Statistics          *content2.ContentStatistics     `json:"statistics"`
	RegulateInfo        map[string]string               `json:"regulate_info"`
	IsNotAllowSend      bool                            `json:"is_not_allow_send"` // 是否不允许发送给端上
	PublishedTime       int64                           `json:"published_time"`
	AuthorUserMeta      *AuthorUserMeta                 `json:"author_user_meta"`
	Similarity          float64                         `json:"similarity"`
	TagInfo             map[string]*tag_core.Tags       `json:"tag_info"`             // 内容的打标信息
	AuthorTagInfo       map[string]*tag_core.Tags       `json:"author_tag_info"`      // 内容创作者的打标信息
	Images              []*Image                        `json:"images"`               // 正文中包含的图片信息
	HashChunkEmbedding  bool                            `json:"hash_chunk_embedding"` // 是否有提前算好的 chunk embedding
	Chunks              []*ItemMeta                     `json:"chunks"`               // doc 选取的 chunk 列表
	Summary             string                          `json:"summary"`              // doc 生成的 summary
	DocumentParsing     *Element                        `json:"document_parsing"`
	Document            *Document                       `json:"document"`        // agent解析的document信息
	ReadParagraphs      map[string][]*DocumentParagraph `json:"read_paragraphs"` // doc 解析出的与intent:chunk
	ReadMeta            bool                            `json:"read_meta"`       // doc 解析出 meta 信息与intent相关
	PrefixCache         sync.Map                        `json:"-"`               // 使用 sync.Map 替代普通 map
	Index               int                             `json:"index"`           // doc 在请求列表中的位置
}

func (i *ItemMeta) GetReadTokenLength() int {
	count := 0
	for _, paragraphs := range i.ReadParagraphs {
		for _, p := range paragraphs {
			count += util.UnicodeLen(p.Content)
		}
	}

	return count
}

type Agent int

const (
	AgentUnknown Agent = 0
	AgentRead    Agent = 1 // read agent
)

func (i *ItemMeta) GetRecallSourceInfo() *RecallSourceInfo {
	if i.RecallSourceInfo == nil {
		return &RecallSourceInfo{}
	}
	return i.RecallSourceInfo
}

func (i *ItemMeta) GetRankInfo() *RankInfo {
	if i.RankInfo == nil {
		return &RankInfo{}
	}
	return i.RankInfo
}

func (i *ItemMeta) GetContentTitle() string {
	var title string
	if i.ContentInfo != nil {
		title = i.ContentInfo.GetTitle()
	}
	if title == "" && i.ParentContentInfo != nil {
		title = i.ParentContentInfo.GetTitle()
	}
	return title
}

func (i *ItemMeta) GenItemKey() string {
	return fmt.Sprintf("%s:%d", i.DocType.String(), i.DocId)
}

func (i *ItemMeta) GetCardDocType() string {
	return macro.DocType2CardDocType(i.DocType)
}

func (i *ItemMeta) GetTitle() string {
	if i.Title != "" {
		return i.Title
	}
	if i.ParentContentInfo != nil {
		return i.ParentContentInfo.GetTitle()
	}
	return ""
}

var innerDocType = []content.DocType_Type{
	content.DocType_Answer,
	content.DocType_Article,
	content.DocType_Member,
	content.DocType_Paper,
	content.DocType_ZhiDaUserUpload,
	content.DocType_Webpage,
	content.DocType_CrawlerWebpage,
	content.DocType_AispUserUpload,
	content.DocType_InternalDoc,
}

func (i *ItemMeta) IsOutLink() bool {
	return !lo.Contains(innerDocType, i.DocType)
}

type RecallSourceInfo struct {
	RecallerName               string
	IndexSource                conf.IndexSourceType
	IndexLevel                 conf.IndexLevelType
	KbSources                  []conf.KbSource
	OrderGroup                 int
	RecallScore                float64
	Enable                     int64
	EmbeddingSource            string
	CrawlerSource              string // 站外爬取来源
	CrawlerSourceType          string // 站外爬取来源类型
	RecallRank                 int    // 召回次序 1-n
	IsPrepareCitable           bool   // 是否预输出角标（最终的数据由后续算子决定Used之后才会去改到外层的） IsCitable
	Used                       bool
	RecallQueryMerge           string                          // 用来召回的 query merge
	KnowledgeBaseId            int64                           // 知识库 ID
	KnowledgeBaseName          string                          // 知识库 Name
	PersonalKnowledgeBaseType  proto.PersonalKnowledgeBaseType // 知识库类型
	KnowledgeBaseVisibility    proto.KnowledgeBaseVisibility   // 知识库可见性
	KnowledgeBaseCreator       int64                           // 知识库创建者 ID
	UniversalKnowledgeBaseType enums.KnowledgeBaseType         // 通用知识库类型
	UniversalKnowledgeBaseName string                          // 通用知识库名称
	UniversalKnowledgeBaseDesc string                          // 通用知识库描述
	Source                     []string                        // 内容来源
	ExtraInfo                  *ExtraInfo                      // 额外信息
}

type ExtraInfo struct {
	RelevanceScore  float64 // 召回相关度得分
	TimelinessScore float64 // 时效性得分
	AuthorityScore  float64 // 权威性得分
	AuthorityLevel  float64 // 权威性等级
	RelevanceLevel  float64 // 相关性等级
}
type RankInfo struct {
	SimilarScore float64
}

func (r RecallSourceInfo) GetFirstKbSource() conf.KbSource {
	if len(r.KbSources) > 0 {
		return r.KbSources[0]
	}
	return ""
}

func (r RecallSourceInfo) ContainSource(target conf.KbSource) bool {
	for _, kbSource := range r.KbSources {
		if kbSource == target {
			return true
		}
	}
	return false
}

func (r RecallSourceInfo) ContainSources(sources []conf.KbSource) bool {
	for _, kbSource := range r.KbSources {
		if lo.Contains(sources, kbSource) {
			return true
		}
	}
	return false
}

// 添加线程安全的 PrefixCache 操作方法
func (i *ItemMeta) GetPrefixCache(agent Agent, key string) (string, bool) {
	agentMap, ok := i.PrefixCache.Load(agent)
	if !ok {
		return "", false
	}

	agentMapTyped, ok := agentMap.(*sync.Map)
	if !ok {
		return "", false
	}

	value, ok := agentMapTyped.Load(key)
	if !ok {
		return "", false
	}

	valueStr, ok := value.(string)
	return valueStr, ok
}

func (i *ItemMeta) SetPrefixCache(agent Agent, key, value string) {
	agentMap, _ := i.PrefixCache.LoadOrStore(agent, &sync.Map{})
	agentMapTyped := agentMap.(*sync.Map)
	agentMapTyped.Store(key, value)
}

func (i *ItemMeta) GetPrefixCacheMap(agent Agent) *sync.Map {
	agentMap, _ := i.PrefixCache.LoadOrStore(agent, &sync.Map{})
	return agentMap.(*sync.Map)
}
