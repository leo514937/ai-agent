package model

const (
	RequestSourceNormal   = "normal"   // 正常来源
	RequestSourceInternal = "internal" // 内网工具服务来源
	RequestSourcePush     = "push"     // Push 请求
)

type QueryPlaylistRequest struct {
	UserID int64  // 用户ID
	Date   string // 快照日期
	Token  string // 客态用户token
	Source string // 请求来源
}
