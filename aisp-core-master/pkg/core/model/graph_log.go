package model

type GraphLogInfoVo struct {
	// 图所在 app 名称
	AppName string
	// 图所在 unit 名称
	UnitName string
	// 图场景
	BusinessName string
	// 图名称
	GraphName string
	// 图版本
	Version string
	// 请求 id
	RequestId string
	// 日志记录时间
	WriteTimestamp int64
	// 日志 key: LogType value: log
	LogMap map[string][]*LogVo
	// 执行图地址
	RuntimeImgPath string
	// 时序图数据
	TimingInfo [][]string
}

type LogVo struct {
	// node name
	NodeName string
	// 日志
	LogStr string
	// 日志写入时间
	LogWriteTime int64
}
