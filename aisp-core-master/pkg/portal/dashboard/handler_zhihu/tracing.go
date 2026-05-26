package handler_zhihu

import (
	"bytes"
	"context"

	"git.in.zhihu.com/go/cafe/rest"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/core/crontab/tracing"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	service "git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/tracing_platform"
	"git.in.zhihu.com/zrec/zrec-utils/safe_group"
)

var tracingPlatformService = service.DefaultTracingPlatformService

type BadCaseTracingListHandler struct {
	rest.BaseHandler
}

func NewBadCaseTracingListHandler() rest.Handler {
	return &BadCaseTracingListHandler{}
}

func (b *BadCaseTracingListHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}

	filterParams, err := buildCommonFilterParams(ctx)
	if err != nil {
		return nil, err
	}

	filterParams.Scene = ctx.QueryArgumentWithFallback("scene", "")
	filterParams.MemberId = ctx.Int64QueryArgument("member_id", 0)
	filterParams.MessageId = ctx.QueryArgumentWithFallback("message_id", "")
	filterParams.RespMessageId = ctx.QueryArgumentWithFallback("resp_message_id", "")
	filterParams.CaseType = ctx.QueryArgumentWithFallback("case_type", "")
	filterParams.FeedbackSource = ctx.QueryArgumentWithFallback("feedback_source", "")
	filterParams.HandlingState = ctx.QueryArgumentWithFallback("handling_state", "")
	filterParams.ToBeResolved = ctx.IntQueryArgument("to_be_resolved", 0)

	result, totalCount, err := tracingPlatformService.ListBadCaseTracing(ctx, filterParams)
	if err != nil {
		return nil, err
	}

	return ResponsePagingSuccess(result, "", int64(totalCount))
}

type BadCaseTracingDownloadHandler struct {
	rest.BaseHandler
}

func NewBadCaseTracingDownloadHandler() rest.Handler {
	return &BadCaseTracingDownloadHandler{}
}

func (b *BadCaseTracingDownloadHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}

	filterParams, err := buildCommonFilterParams(ctx)
	if err != nil {
		return nil, err
	}

	// 一次最多下载 1k 条
	filterParams.Page = 0
	filterParams.PageSize = 1000

	filterParams.Scene = ctx.QueryArgumentWithFallback("scene", "")
	filterParams.MemberId = ctx.Int64QueryArgument("member_id", 0)
	filterParams.MessageId = ctx.QueryArgumentWithFallback("message_id", "")
	filterParams.RespMessageId = ctx.QueryArgumentWithFallback("resp_message_id", "")
	filterParams.CaseType = ctx.QueryArgumentWithFallback("case_type", "")
	filterParams.FeedbackSource = ctx.QueryArgumentWithFallback("feedback_source", "")
	filterParams.HandlingState = ctx.QueryArgumentWithFallback("handling_state", "")
	filterParams.ToBeResolved = ctx.IntQueryArgument("to_be_resolved", 0)

	result, _, err := tracingPlatformService.ListBadCaseTracing(ctx, filterParams)
	if err != nil {
		return nil, err
	}

	excelFile, excelErr := tracingPlatformService.WriteExcel(ctx, result)
	if excelErr != nil {
		return nil, excelErr
	}

	// 将Excel文件保存到内存中
	buffer := new(bytes.Buffer)
	if err := excelFile.Write(buffer); err != nil {
		return nil, err
	}

	// 设置下载相关的header
	ctx.Writer.Header().Set("Content-Disposition", "attachment; filename=badcase.xlsx")
	ctx.Writer.Header().Set("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

	// 将Excel文件内容写入HTTP响应
	_, err = ctx.Writer.Write(buffer.Bytes())
	if err != nil {
		return nil, err
	}

	return EmptyResult, nil
}

type BadCaseTracingProcessHandler struct {
	rest.BaseHandler
}

func NewBadCaseTracingProcessHandler() rest.Handler {
	return &BadCaseTracingProcessHandler{}
}

func (b *BadCaseTracingProcessHandler) Get(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityRead)
	if err != nil {
		return nil, err
	}

	traceId := ctx.QueryArgumentWithFallback("trace_id", "")

	result, err := tracingPlatformService.GetBadCaseProcess(ctx, traceId)
	if err != nil {
		return BaseResponse{
			Success: false,
			Msg:     "结果为空",
			Data:    &model.BadcaseTracingProcess{},
		}, nil
	}

	return ResponseSuccess(result)
}

type BadCaseTracingInsertHandler struct {
	rest.BaseHandler
}

func NewBadCaseTracingInsertHandler() rest.Handler {
	return &BadCaseTracingInsertHandler{}
}

func (b *BadCaseTracingInsertHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}

	var filterParams *model.BadcaseTracingFilterParams
	err = ctx.JSONArgs(&filterParams)
	if err != nil {
		return nil, err
	}

	if filterParams.TraceId == "" || filterParams.RequestTime == "" {
		return BaseResponse{
			Success: false,
			Msg:     "trace_id和request_time均不能为空",
			Data:    nil,
		}, nil
	}

	isExist := tracingPlatformService.IsBadCaseRecordExist(ctx, filterParams.TraceId)
	if isExist {
		return BaseResponse{
			Success: false,
			Msg:     "记录已存在",
			Data:    nil,
		}, nil
	}

	if insertErr := tracingPlatformService.AddBadCaseTracing(ctx, filterParams); insertErr != nil {
		return BaseResponse{
			Success: false,
			Msg:     "添加记录失败",
			Data:    nil,
		}, insertErr
	}

	// 异步进行数据写入，为防止 hive 计算或数据拉取失败，加 3 次重试
	safe_group.SafeGo(func() error {
		retryTimes := 3
		for i := 0; i < retryTimes; i++ {
			err := tracingPlatformService.AddBadCaseTracingAsync(context.Background(), filterParams)
			if err == nil {
				break
			}
		}
		return nil
	}, "Add BadCase Record")

	return ResponseSuccess(nil)
}

type BadCaseTracingUpdateHandler struct {
	rest.BaseHandler
}

func NewBadCaseTracingUpdateHandler() rest.Handler {
	return &BadCaseTracingUpdateHandler{}
}

func (b *BadCaseTracingUpdateHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}

	var badCaseTracingRecord *model.BadcaseTracingList
	err = ctx.JSONArgs(&badCaseTracingRecord)
	if err != nil {
		return nil, err
	}

	if badCaseTracingRecord.TraceId == "" {
		return BaseResponse{
			Success: false,
			Msg:     "trace_id不能为空",
			Data:    nil,
		}, nil
	}

	err = tracingPlatformService.UpdateBadCaseTracing(ctx, badCaseTracingRecord)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(nil)
}

type BadCaseTracingDeleteHandler struct {
	rest.BaseHandler
}

func NewBadCaseTracingDeleteHandler() rest.Handler {
	return &BadCaseTracingDeleteHandler{}
}

func (b *BadCaseTracingDeleteHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}

	var badCaseTracingRecord *model.BadcaseTracingList
	err = ctx.JSONArgs(&badCaseTracingRecord)
	if err != nil {
		return nil, err
	}

	if badCaseTracingRecord.TraceId == "" {
		return BaseResponse{
			Success: false,
			Msg:     "trace_id不能为空",
			Data:    nil,
		}, nil
	}

	err = tracingPlatformService.DeleteBadCaseTracing(ctx, badCaseTracingRecord)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(nil)
}

type BadCaseTracingUpdateToBeResolvedHandler struct {
	rest.BaseHandler
}

func NewBadCaseTracingUpdateToBeResolvedHandler() rest.Handler {
	return &BadCaseTracingUpdateToBeResolvedHandler{}
}

func (b *BadCaseTracingUpdateToBeResolvedHandler) Post(ctx *rest.Context) (rest.Response, error) {
	err := checkAuthority(ctx, operation_base.AuthorityEdit)
	if err != nil {
		return nil, err
	}

	var badCaseTracingRecord *model.BadcaseTracingList
	err = ctx.JSONArgs(&badCaseTracingRecord)
	if err != nil {
		return nil, err
	}

	if badCaseTracingRecord.TraceId == "" {
		return BaseResponse{
			Success: false,
			Msg:     "trace_id不能为空",
			Data:    nil,
		}, nil
	}

	err = tracingPlatformService.UpdateBadCaseToBeResolved(ctx, badCaseTracingRecord)
	if err != nil {
		return nil, err
	}

	return ResponseSuccess(nil)
}
