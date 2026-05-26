package model

type Config struct {
	ChatType          string `json:"type"`
	MaxLength         int
	RepetitionPenalty float32
	NgramPenalty      float32
	Temperature       float32
	TopP              float32
	Seed              int
}
type ChatNew80BModelReq struct {
	Query     string
	Instances []string
	Config    Config
	Params    Config
}
