package module

// ContentActivityEvent 结构体对应于给定的 JSON 数据。
type ContentActivityEvent struct {
	Action      string `json:"Action"`
	ActionTime  int64  `json:"ActionTime"`
	ActionType  int64  `json:"ActionType"`
	ContentId   string `json:"ContentId"`
	ContentType string `json:"ContentType"`
	Id          int64  `json:"Id"`
	OutId       string `json:"OutId"`
	UrlToken    string `json:"UrlToken"`
}
