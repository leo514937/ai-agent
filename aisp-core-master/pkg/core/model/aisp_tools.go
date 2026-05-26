package model

type AispToolsItem struct {
	SubTaskId string   `json:"sub_task_id"`
	Name      string   `json:"name"`
	ItemType  string   `json:"item_type"`
	Version   string   `json:"version"`
	Text      string   `json:"text"`
	Element   *Element `json:"element"`
}

type Element struct {
	Id      int64       `json:"id"`
	Type    string      `json:"type"`
	Text    string      `json:"text"`
	Rbounds []float64   `json:"rbounds"`
	Boxes   [][]float64 `json:"boxes"`
	Pages   []float64   `json:"pages"`
}

func (i *AispToolsItem) GetText() string {
	if i.Element != nil && i.Element.Text != "" {
		return i.Element.Text
	}
	return i.Text
}

type AispToolsItems struct {
	Items []*AispToolsItem `json:"items"`
}

type AispToolsResponse struct {
	Status string          `json:"status"`
	Data   *AispToolsItems `json:"data"`
}

type ComplexResponse struct {
	Markdown string     `json:"markdown"`
	Elements []*Element `json:"elements"`
}

type MarkdownResponse struct {
	Markdown string `json:"markdown"`
}

type ImageResponse struct {
	Original string `json:"original"`
	Summary  string `json:"summary"`
}

// ParsedContent 解析后的内容结构
type HtmpParseResponse struct {
	Markdown string                 `json:"markdown"`
	Version  string                 `json:"version"`
	Blocks   []*ContentBlock        `json:"blocks"`
	Images   map[string][]*ImageRef `json:"images"`
}

// ContentBlock 内容块结构
type ContentBlock struct {
	ID      string `json:"id"`
	Type    string `json:"type"`
	Content string `json:"content"`
}

// ImageRef 图片引用结构
type ImageRef struct {
	Token  string `json:"token"`
	Title  string `json:"title"`
	Marker string `json:"marker"`
}
