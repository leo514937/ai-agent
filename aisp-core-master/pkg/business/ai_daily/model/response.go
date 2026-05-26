package model

type InternalResponseData struct {
	Date     string                 `json:"date"`
	UserName string                 `json:"user_name"`
	Datas    []*RedisQuestionDetail `json:"datas"`
}

type Response struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data"`
}

type PlaylistHistoryResponse struct {
	TotalCount int      `json:"total_count"`
	Items      []string `json:"items"`
}

type QuestionItem struct {
	DocType  string        `json:"doc_type"`
	Title    string        `json:"title"`
	Detail   string        `json:"detail"`
	Url      string        `json:"url"`
	UrlToken string        `json:"url_token"`
	Items    []*AnswerItem `json:"content_summary"`
}

type AnswerItem struct {
	DocType      string `json:"doc_type"`
	AuthorName   string `json:"author_name"`
	AuthorUrl    string `json:"author_url"`
	AuthorHashID string `json:"author_hash_id"`
	Detail       string `json:"detail"`
	Url          string `json:"url"`
	UrlToken     string `json:"url_token"`
}

type QueryPlaylistResponse struct {
	Title      string          `json:"title"`
	Date       string          `json:"date"`
	ShareToken string          `json:"share_token"`
	Contents   []*QuestionItem `json:"items"`
}
