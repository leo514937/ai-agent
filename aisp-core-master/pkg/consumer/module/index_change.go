package module

import (
	"git.in.zhihu.com/pb-go/zai-proto/ai/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
)

type IndexChangeKafkaMsg struct {
	RequestId          string        `json:"request_id"`
	KnowledgeId        int64         `json:"knowledge_id"`
	DocId              int64         `json:"doc_id"`
	DocType            string        `json:"doc_type"` // zai-proto/ai/content/doc.proto 里 docType.string
	Title              string        `json:"title"`    // 文章给自身标题，回答给问题标题
	Text               string        `json:"text"`     // P0级知识库用户填写内容
	AuthorId           int64         `json:"author_id"`
	BayesFirstCategory []string      `json:"bayes_first_category"`
	BizType            model.BizType `json:"biz_type"`
	MethodType         MethodType    `json:"method_type"`
	TimeStampMs        int64         `json:"time_stamp_ms"`
	OpType             OpType        `json:"op_type"`
}

type OpType string

const (
	Batch  OpType = "BATCH"
	Single OpType = "SINGLE"
)

type MethodType string

const (
	Upsert MethodType = "UPSERT"
	Delete MethodType = "DELETE"
)

type IndexChangeCallBackKafkaMsg struct {
	MessageId   string        `json:"message_id"`
	KnowledgeId int64         `json:"knowledge_id"`
	DocId       int64         `json:"doc_id"`
	DocType     string        `json:"doc_type"` // zai-proto/ai/content/doc.proto 里 docType.string
	AuthorId    int64         `json:"author_id"`
	BizType     model.BizType `json:"biz_type"`
	MethodType  MethodType    `json:"method_type"`
	Status      Status        `json:"status"`
	TimeStampMs int64         `json:"time_stamp_ms"`
}

type Status struct {
	Code    int32  `json:"code"` // 成功为0
	Name    string `json:"name"`
	Message string `json:"message"`
}

type HotCrawlerKafkaMsg struct {
	Title       string `json:"title"`        // 标题
	Content     string `json:"content"`      // 正文
	Domain      string `json:"domain"`       // 领域
	BizType     string `json:"biz_type"`     // 业务类型，例如热点
	LinkUrl     string `json:"link_url"`     // 网站 url 地址
	Source      string `json:"source"`       // 来源
	SourceType  string `json:"source_type"`  // 来源类型
	PublishTime int64  `json:"publish_time"` // 发布时间
	CrawlerTime int64  `json:"crawler_time"` // 采集时间
	Priority    int64  `json:"priority"`     // 优先级
	WebSource   string `json:"web_source"`   // 文章数据来源
	Rank        int64  `json:"rank"`         // 榜单排名
	SpecialTag  string `json:"special_tag"`  // 自定义标签
}

type CrawlerWebpageKafkaMsg struct {
	DocId            int64                `json:"doc_id"`
	DocType          content.DocType_Type `json:"doc_type"`
	ObjectId         string               `json:"object_id"`
	Title            string               `json:"title"`
	LinkUrl          string               `json:"link_url"`
	MetaUrl          string               `json:"meta_url"`
	Source           string               `json:"source"`
	Content          string               `json:"content"`
	Domain           string               `json:"domain"`
	PublishTime      int64                `json:"publish_time"`
	IsCrawlerAllowed bool                 `json:"is_crawler_allowed"`
	CrawlerTime      int64                `json:"crawler_time"`
	OtherInfo        string               `json:"other_info"`
	Abstract         string               `json:"abstract"`
}
