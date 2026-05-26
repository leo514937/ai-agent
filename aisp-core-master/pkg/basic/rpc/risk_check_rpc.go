package rpc

import (
	"context"

	"git.apache.org/thrift.git/lib/go/thrift"
	"git.in.zhihu.com/one-rpc-go/thrift-eval-regulate-core/eval_regulate_core_thrift/risk_check"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"github.com/spf13/cast"
)

type RiskCheckRPC interface {

	// RiskCheckInterestWord 安全审核兴趣词
	RiskCheckInterestWord(ctx context.Context, word string, source string) (*RiskCheckResp, error)

	// RiskCheckDialog 安全审核多轮对话
	RiskCheckDialog(ctx context.Context, params *RiskCheckParams) (*RiskCheckResp, error)

	// RiskCheckRecallTitleAbstract 安全审核参考文献标题摘要
	RiskCheckRecallTitleAbstract(ctx context.Context, dto RiskCheckRecallDto) (*RiskCheckResp, error)

	// RiskCheckDeepSearch 安全审核深度搜索的 goal、queries、summary
	RiskCheckDeepSearch(ctx context.Context, dto RiskCheckDeepSearchDto) (*RiskCheckResp, error)
}

type RiskCheckParams struct {
	// 用户Id
	MemberId int64
	// DeviceId 设备Id
	DeviceId string
	// IP IP地址
	IP string
	// user-agent
	UserAgent string
	// SourceId
	SourceId RiskCheckSourceId
	// Scene 场景
	Scene string
	// ClientSource 客户端来源
	ClientSource string
	// TrafficSource 流量来源
	TrafficSource string
	// ChatModel 模型名称
	ChatModel string
	// DataSourceType 专业版数据来源
	DataSourceType string
	// 内容
	Contents []*risk_check.CheckContentDetail
	// Query 需要对应 SourceId 为 对话场景 目前只是需要在 merge 场景 配置使用
	// 回答 (如果不是回答 可不传)
	QueryExtra *risk_check.QuestionInfo
	// Answer 需要对应 SourceId 为 对话场景
	// 回答 (如果不是回答 可不传)
	AnswerExtra *risk_check.AnswerInfo
}

type RiskCheckRecallDto struct {
	Source      string
	Url         string
	Query       string
	Title       string
	Abstract    string
	FullContent string
	// Extra 信息
	MemberId     int64
	UserIp       string
	SessionId    string
	QuestionId   string
	QuestionText string
	// ClientSource 客户端来源
	ClientSource string
	// TrafficSource 流量来源
	TrafficSource string
	// ChatModel 模型名称
	ChatModel string
}

type RiskCheckDeepSearchDto struct {
	MemberId      int64
	QuestionId    string
	Goal          string
	SearchKeyWord string
	RecallSummary string
}

type RiskCheckResp struct {
	// 判断结果
	Res RiskCheckRes
	// 对应 Action
	Action int64
}

// NewRiskAnswerInfo 默认创建 answer 信息
func NewRiskAnswerInfo() *risk_check.AnswerInfo {
	return &risk_check.AnswerInfo{
		AnswerType:     thrift.StringPtr(RiskCheckAnswerTypeConv.ToConvert()),
		IsStreamAnswer: thrift.BoolPtr(false),
		IsLast:         thrift.BoolPtr(true),
		IsFixedAnswer:  thrift.BoolPtr(false),
	}
}

const (
	RiskCheckAppID       = "1001"
	RiskCheckSuccessCode = 200
)

type RiskCheckSourceId int64

func (r RiskCheckSourceId) ToConvert() int64 {
	return int64(r)
}

func (r RiskCheckSourceId) ToConvertStr() string {
	return cast.ToString(r.ToConvert())
}

// RiskCheckRes 结果建议动作，1:通过，2:疑似，0:不通过
type RiskCheckRes int64

func (r RiskCheckRes) ToConvert() int64 {
	return int64(r)
}

// RiskCheckQuestionType 请求附加类型
type RiskCheckQuestionType string

func (r RiskCheckQuestionType) ToConvert() string {
	return string(r)
}

// RiskCheckAnswerType 回答附加类型
type RiskCheckAnswerType string

func (r RiskCheckAnswerType) ToConvert() string {
	return string(r)
}

// Source 赋值
const (
	// RiskCheckSourceTest
	RiskCheckSourceTest RiskCheckSourceId = 90005
	// RiskCheckSourceSearchQueryAndMerge SearchTab eval的多轮场景ID 包含用户Query 和 Merge
	RiskCheckSourceSearchQueryAndMerge RiskCheckSourceId = 150015
	// RiskCheckSourceDigitalAuthorQuery 数字分身 eval的多轮场景ID 包含用户Query
	RiskCheckSourceDigitalAuthorQuery RiskCheckSourceId = 150018
	// RiskCheckSourceZplusBrandQuery 知加品牌直答 eval的多轮场景ID 包含用户Query
	RiskCheckSourceZplusBrandQuery RiskCheckSourceId = 570002
	// RiskCheckSourceZplusRumorsQuery 知加辟谣助手 eval的多轮场景ID 包含用户Query
	RiskCheckSourceZplusRumorsQuery RiskCheckSourceId = 570004
	// RiskCheckSourceSearchAnswer SearchTab eval的多轮场景ID 包含用户回答
	RiskCheckSourceSearchAnswer RiskCheckSourceId = 90031
	// RiskCheckSourceDigitalAuthorAnswer 数字分身 eval的多轮场景ID 包含大模型回答
	RiskCheckSourceDigitalAuthorAnswer RiskCheckSourceId = 90032
	// RiskCheckSourceZplusBrandAnswer 知加品牌直答 eval的多轮场景ID 包含大模型回答
	RiskCheckSourceZplusBrandAnswer RiskCheckSourceId = 570003
	// RiskCheckSourceZplusRumorsAnswer 知加辟谣助手 eval的多轮场景ID 包含大模型回答
	RiskCheckSourceZplusRumorsAnswer RiskCheckSourceId = 600003
	// RiskCheckSourceAiQuery 自由对话场景 eval的多轮场景ID 包含 用户提问
	RiskCheckSourceAiQuery RiskCheckSourceId = 90030
	// RiskCheckSourceAiAnswer  自由对话场景 eval的多轮场景ID 包含 Ai回答
	RiskCheckSourceAiAnswer RiskCheckSourceId = 32
	// RiskCheckSourceZhihaituQuery 知海图query场景。见：https://zhihu.kdocs.cn/l/cshOA5QYGMfx
	RiskCheckSourceZhihaituQuery RiskCheckSourceId = 30007
	// RiskCheckSourceZhihaituAnswer 知海图answer场景。见：https://zhihu.kdocs.cn/l/cshOA5QYGMfx
	RiskCheckSourceZhihaituAnswer RiskCheckSourceId = 30008
)

// Res 赋值
const (
	RiskCheckResUnPass    RiskCheckRes = 0
	RiskCheckResPass      RiskCheckRes = 1
	RiskCheckResSuspected RiskCheckRes = 2
)

// RiskCheckQuestionType 赋值
const (
	RiskCheckQuestionTypeUser RiskCheckQuestionType = "user"
	RiskCheckQuestionTypeAlgo RiskCheckQuestionType = "algo"
)

// RiskCheckAnswerType 赋值
const (
	RiskCheckAnswerTypeConv RiskCheckAnswerType = "conv"
)

var RoleTypeMap = make(map[string]string)

func init() {
	RoleTypeMap[model.RoleTypeAI.ToConvert()] = "SYSTEM"
	RoleTypeMap[model.RoleTypeUser.ToConvert()] = "USER"
}
