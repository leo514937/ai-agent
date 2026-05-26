package model

import (
	"bytes"
	"text/template"
	"time"

	util2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/req_macro"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

type PromptTemplate struct {
	ID        int64               `json:"id"`
	IDString  string              `json:"id_string"`
	TenantID  int64               `json:"tenant_id"`
	TaskID    int64               `json:"task_id"`
	State     PromptTemplateState `json:"state"`
	Template  string              `json:"template"`
	CreatedAt time.Time           `json:"created_at"`
	UpdatedAt time.Time           `json:"updated_at"`
}

type PromptTemplateState string

const (
	PromptTemplateStateNormal  PromptTemplateState = "NORMAL"
	PromptTemplateStateDeleted PromptTemplateState = "DELETED"
)

const (
	KnowledgeBaseTypeZhihuAnswerAndArticleAndPaper = 1
	KnowledgeBaseTypeZhihuAuthor                   = 2
	KnowledgeBaseTypeWeb                           = 3
	KnowledgeBaseTypeUserUpLoad                    = 4
)

type PromptInputKnowledgeBase struct {
	RecallIndex                int
	DocTitle                   string
	DocPublishedTimeFormatStr  string
	Text                       string
	IsOutLink                  bool
	Type                       int // 1:知乎回答或者文章，2：知乎答主，3：网页
	DocType                    string
	AuthorUrl                  string
	Url                        string
	UniversalKnowledgeBaseName string  // 通用知识库名称
	UniversalKnowledgeBaseDesc string  // 通用知识库描述
	AnswerProperty             string  // 知乎回答属性
	Timeliness                 float64 //时效性
	RelevanceScore             float64 //相关性
	AuthorityScore             float64 //权威性
	AuthorityLevel             float64 //权威性等级
	RelevanceLevel             float64 //相关性等级
}

type QueryDefinition struct {
	Definition  string
	DocTitle    string
	DocTypeText string
}

type PromptInput struct {
	Query                            string
	QueryMerge                       string
	QueryDefinition                  QueryDefinition
	Knowledge                        string
	FullKnowledge                    string
	KnowledgeBase                    []*PromptInputKnowledgeBase
	KnowledgeBaseInfo                []*KnowledgeBaseInfo
	AuthorMetaInfo                   []*AuthorInfo
	SearchSourceMap                  map[string][]*req_macro.SourceInfo
	UniversalKnowledgeBaseInfo       []*UniversalKnowledgeBaseInfo
	SystemUniversalKnowledgeBaseInfo []*UniversalKnowledgeBaseInfo // 系统通用知识库
	UserUniversalKnowledgeBaseInfo   []*UniversalKnowledgeBaseInfo // 用户通用知识库
	ModelName                        string                        // 模型名称
	IsPureDocs                       bool                          // 是否是纯文档
	AuthorName                       string
	Answer                           string
	IsChineseByQueryAndAnswer        bool
	AuthorIds                        string
	Bayes                            string
	Topic                            string
	Task                             string
	Date                             string
	OneWeekDay                       string
	Weekday                          string
	Time                             string
	Yesterday                        string
	Tomorrow                         string
	YesterdayWeekday                 string
	TommorrowWeekday                 string
	Year                             string
	LastYear                         string
	NextYear                         string
	Now                              string
	IndexLevel                       string
	BrandDescription                 string
	Title                            string
	DocumentInfo                     *DocumentPromptInfo
	Specification                    string
	FavBaseCount                     int
	DocCount                         int
}

type DocumentPromptInfo struct {
	DocumentType    string                 // 文档类型
	DocumentTitle   string                 // 文档标题
	DocumentDate    string                 // 发布日期
	DocumentAddDate string                 // 添加日期
	DocumentAuthor  string                 // 作者
	DocumentLink    string                 // 链接
	DocumentSources string                 // 来源
	DocumentStats   map[string]interface{} // 统计信息
	Paragraphs      []*DocumentParagraph   // 段落列表
	Pids            []int                  // 当前块包含的段落ID列表
}

// GenPrompt 时间相关的变量提供了默认值
func GenPrompt(promptInput *PromptInput, promptFmt string, promptId string) (string, error) {
	promptTemplate := &PromptTemplate{
		ID:       cast.ToInt64(promptId),
		IDString: promptId,
		Template: promptFmt,
	}

	// 创建FuncMap以添加自定义函数
	funcMap := template.FuncMap{
		"addOne": func(i int) int {
			return i + 1
		},
		"addOffset": func(i, offset int) int {
			return i + offset
		},
		"UnicodeLen": func(str string) int {
			var r = []rune(str)
			return len(r)
		},
		"UnicodeSubstr": func(str string, start, length int) string {
			return string(lo.Slice([]rune(str), start, start+length))
		},
	}

	// 拼接 prompt
	templateObj, err := template.New(promptId).Funcs(funcMap).Parse(promptTemplate.Template)
	if err != nil {
		return "", err
	}

	promptBuffer := &bytes.Buffer{}

	if promptInput.Date == "" {
		promptInput.Date = util2.GetNowDate()
	}
	if promptInput.Weekday == "" {
		promptInput.Weekday = util2.GetNowWeek()
	}
	if promptInput.Time == "" {
		promptInput.Time = util2.GetNowTime()
	}
	if promptInput.Yesterday == "" {
		promptInput.Yesterday = util2.PlusDate(-1)
	}
	if promptInput.Tomorrow == "" {
		promptInput.Tomorrow = util2.PlusDate(1)
	}
	if promptInput.OneWeekDay == "" {
		promptInput.OneWeekDay = util2.PlusDate(7)
	}
	if promptInput.YesterdayWeekday == "" {
		promptInput.YesterdayWeekday = util2.GetWeekDay(-1)
	}
	if promptInput.TommorrowWeekday == "" {
		promptInput.TommorrowWeekday = util2.GetWeekDay(1)
	}
	if promptInput.Year == "" {
		promptInput.Year = util2.GetNowYear()
	}
	if promptInput.LastYear == "" {
		promptInput.LastYear = util2.PlusYear(-1)
	}
	if promptInput.NextYear == "" {
		promptInput.NextYear = util2.PlusYear(1)
	}

	err = templateObj.Execute(promptBuffer, promptInput)
	if err != nil {
		return "", err
	}

	return promptBuffer.String(), nil
}
