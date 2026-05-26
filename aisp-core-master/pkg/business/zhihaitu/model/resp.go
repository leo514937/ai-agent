package model

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/zhihaitu/constant"
)

type CommonResp struct {
	Success bool   `json:"success"`
	Msg     string `json:"msg"`
}
type AccountLoginResp struct {
	CommonResp
	Mobile    string `json:"mobile"`
	Token     string `json:"token"`
	UserId    int64  `json:"userId"`
	Name      string `json:"name"`
	UserIdent string `json:"userIdent"`
}

type SafeAuditResp struct {
	MsgId      string `json:"msgId"`
	ChildMsgId string `json:"childMsgId"`
	State      string `json:"state"`
}

type MessageState struct {
	Tip string
}

type MessageInfo struct {
	MsgId          string           `json:"msgId"`
	MsgType        MessageType      `json:"msgType"`
	Output         string           `json:"output"`
	CostTimeMillis int64            `json:"costTimeMillis"`
	MsgStates      []*MessageState  `json:"msgStates"`
	State          MessageTaskState `json:"state"`
	StopEnum       MsgStopEnum      `json:"stopEnum"`
}

type UserSuggestion struct {
	AccountId    int64  `json:"accountId"`
	AppId        string `json:"appId"`
	AuditContent string `json:"auditContent"`
	AuditTime    string `json:"auditTime"`
	Content      string `json:"content"`
	CreateTime   string `json:"createTime"`
	ID           string `json:"id"`
	Numbered     string `json:"numbered"`
	Status       string `json:"status"`
	UpdateTime   string `json:"updateTime"`
}

type ReportMessage struct {
	Id           int64  `json:"id"`
	AiContent    string `json:"aiContent"`
	CreateTime   string `json:"createTime"`
	ReportNo     string `json:"reportNo"`
	ReportReason string `json:"reportReason"`
	ReportState  string `json:"reportState"`
}

type ReportMsgInfo struct {
	ReportMsgInfos []*ReportMessage `json:"reportMsgInfos"`
}

type ConvMessage struct {
	Content       string  `json:"content"`       // 消息内容
	CostTimeMilli int64   `json:"costTimeMilli"` // 响应时间
	FeedbackMsg   *string `json:"feedbackMsg"`   // 反馈意见
	MsgID         string  `json:"msgId"`         // 消息id
	MsgType       string  `json:"msgType"`       // 对话类型
	ParentMsgID   string  `json:"parentMsgId"`   // 父消息ID
	Rating        string  `json:"rating"`        // 评级，1-顶，2-踩
	Role          string  `json:"role"`          // 角色，1-AI，2-用户
	State         string  `json:"state"`         // 处理状态
}

type GetMsgsByConvIDResp struct {
	MsgInfos []*ConvMessage `json:"msgInfos"`
}

type OpenApiConvResp struct {
	Content string `json:"content"`
	Status  string `json:"status"`
	Reason  string `json:"reason"`
}

type ResponseStatus struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}
type Response struct {
	ResponseStatus
	RequestId string      `json:"requestId"`
	Data      interface{} `json:"data"`
}

func NewSuccessResponseByData(ctx context.Context, data interface{}) Response {
	traceId, ok := ctx.Value(constant.TraceId).(string)
	if !ok {
		traceId = ""
	}
	return Response{
		ResponseStatusSuccess,
		traceId,
		data,
	}
}

func NewResponseByStatus(ctx context.Context, status ResponseStatus) Response {
	traceId, ok := ctx.Value(constant.TraceId).(string)
	if !ok {
		traceId = ""
	}
	return Response{
		status,
		traceId,
		nil,
	}
}

var ResponseStatusSuccess = ResponseStatus{0, "success"}
var ResponseStatusError = ResponseStatus{-1, "error"}
var ResponseStatusAccountUnauthorizedError = ResponseStatus{1021, "账号未授权"}
var ResponseStatusMobilePatternError = ResponseStatus{1014, "手机号输入非法"}
var ResponseStatusSmsCodePatternError = ResponseStatus{1015, "验证码输入非法"}
var ResponseStatusUserNotExistsError = ResponseStatus{1017, "账号不存在"}
var ResponseStatusNotAuthingError = ResponseStatus{1021, "账号未授权"}
var ResponseStatusParamError = ResponseStatus{2004, "参数错误"}
var ResponseStatusInnerError = ResponseStatus{4002, "服务器繁忙，请稍后重试"}
var ResponseStatusServerError = ResponseStatus{2003, "服务内部错误，请稍后重试"}
