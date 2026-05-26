package model

import "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"

// Document 文档结构体，对应Python代码中的Document类
type Document struct {
	Title         string                 `json:"title"`          // 标题
	Abstract      string                 `json:"abstract"`       // 摘要
	AuthorName    string                 `json:"author_name"`    // 作者姓名
	URL           string                 `json:"url"`            // URL
	Sources       string                 `json:"sources"`        // 来源，逗号分隔
	Paragraphs    []*DocumentParagraph   `json:"paragraphs"`     // 段落列表
	AuthorID      int64                  `json:"author_id"`      // 作者ID
	DatePublished string                 `json:"date_published"` // 发布日期，格式：YYYYMMDD
	DateAdded     string                 `json:"date_added"`     // 添加日期，格式：YYYYMMDD
	Stats         map[string]interface{} `json:"stats"`          // 统计信息
}

// DocumentParagraph 文档段落结构体
type DocumentParagraph struct {
	ID      int    `json:"id"`      // 段落ID
	Content string `json:"content"` // 段落内容
}

func (d *Document) GetTokenLength() int {
	count := 0
	for _, p := range d.Paragraphs {
		count += util.UnicodeLen(p.Content)
	}

	return count
}
