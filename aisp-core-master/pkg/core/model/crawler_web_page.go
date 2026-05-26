package model

import "time"

type CrawlerWebPageKey struct {
	DocId   int64  `json:"content_id" db:"doc_id"`     // 内容id
	DocType string `json:"content_type" db:"doc_type"` // 内容类型
}

type CrawlerWebPage struct {
	DocId            int64     `json:"doc_id" borm:"primary_key"`   // 内容id
	DocType          string    `json:"doc_type" borm:"primary_key"` // 内容类型
	ObjectId         string    `json:"object_id"`                   // object_id
	Title            string    `json:"title"`                       // 网站标题
	MetaUrl          string    `json:"meta_url"`                    // url
	Source           string    `json:"source"`                      // 网站名字
	SourceLevel      int       `json:"source_level"`                // 网站等级
	Content          string    `json:"content"`                     // 网站内容，无html标签
	Domain           string    `json:"domain"`                      // 网站领域
	PublishTime      int64     `json:"publish_time"`                // 网页发布时间
	IsCrawlerAllowed int       `json:"is_crawler_allowed"`          // 网页是否允许被爬，0：不允许，1：允许
	CrawlerTime      int64     `json:"crawler_time"`                // 秒级时间戳
	ExtraInfo        string    `json:"extra_info"`                  // 额外信息
	CreatedAt        time.Time `json:"created_at" borm:"readonly"`  // 创建时间(ms)
	UpdatedAt        time.Time `json:"updated_at" borm:"readonly"`  // 更新时间(ms)
}
