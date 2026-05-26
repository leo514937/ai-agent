package service

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/operation_base"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/service/tracing_log"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/golang/protobuf/jsonpb"
	"github.com/tealeg/xlsx"
)

type TracingPlatformService interface {
	// ListBadCaseTracing 【badcase 平台】查看列表
	ListBadCaseTracing(ctx context.Context, params *model.FilterParams) ([]*model.BadcaseTracingList, int, error)
	// GetBadCaseProcess 【badcase 平台】查看单条 case 的中间过程
	GetBadCaseProcess(ctx context.Context, traceId string) (*model.BadcaseTracingProcess, error)
	// AddBadCaseTracingAsync 【badcase 平台】新增 badcase 记录，异步处理全量数据
	AddBadCaseTracingAsync(ctx context.Context, params *model.BadcaseTracingFilterParams) error
	// AddBadCaseTracing 【badcase 平台】新增 badcase 记录，同步处理少量数据
	AddBadCaseTracing(ctx context.Context, params *model.BadcaseTracingFilterParams) error
	// UpdateBadCaseTracing 【badcase 平台】更新 badcase 状态，包括：处理状态、处理人、处理结果
	UpdateBadCaseTracing(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error
	// UpdateBadCaseToBeResolved 【badcase 平台】更新 badcase 待解决与否的状态
	UpdateBadCaseToBeResolved(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error
	// DeleteBadCaseTracing 【badcase 平台】删除 badcase 记录
	DeleteBadCaseTracing(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error
	// WriteExcel 【badcase 平台】导出 badcase 记录
	WriteExcel(ctx context.Context, badCaseTracingList []*model.BadcaseTracingList) (*xlsx.File, error)
	// IsBadCaseRecordExist 【badcase 平台】判断 badcase 记录是否存在
	IsBadCaseRecordExist(ctx context.Context, traceId string) bool
}

type TracingPlatformServiceImpl struct {
	badcaseTracingDao dao.BadCaseTracingDao
	tracingLogService tracing_log.TracingLogService
}

var (
	DefaultTracingPlatformService TracingPlatformService
)

func init() {
	DefaultTracingPlatformService = newTracingPlatformServiceImpl()
}

func newTracingPlatformServiceImpl() *TracingPlatformServiceImpl {
	return &TracingPlatformServiceImpl{
		badcaseTracingDao: daoImpl.DefaultBadCaseTracingDaoImpl,
		tracingLogService: tracing_log.DefaultTracingLogService,
	}
}

func (t *TracingPlatformServiceImpl) ListBadCaseTracing(ctx context.Context, params *model.FilterParams) ([]*model.BadcaseTracingList, int, error) {
	// 将 model.FilterParams 转换为 model.BadcaseTracingFilterParams
	var chatScenes []string
	for _, scene := range strings.Split(params.Scene, ",") {
		if pbScene, exist := operation_base.SceneToPbNameMap[scene]; exist {
			chatScenes = append(chatScenes, pbScene)
		}
	}

	badCaseTracingFilterParams := &model.BadcaseTracingFilterParams{
		Page:              params.Page,
		PageSize:          params.PageSize,
		ChatScene:         chatScenes,
		MemberId:          params.MemberId,
		RequestMessageId:  params.MessageId,
		ResponseMessageId: params.RespMessageId,
		RequestQuery:      params.Query,
		CaseType:          params.CaseType,
		FeedbackSource:    params.FeedbackSource,
		HandlingState:     model.HandlingStateType(params.HandlingState),
		FeedbackStartTime: params.CreatedAtBegin,
		FeedbackEndTime:   params.CreatedAtEnd,
		State:             params.State,
		ToBeResolved:      params.ToBeResolved,
	}

	// 查询全部即为不带条件检索
	if badCaseTracingFilterParams.HandlingState == model.AllHandlingState {
		badCaseTracingFilterParams.HandlingState = ""
	}

	badCaseTracingList, totalCount, err := t.badcaseTracingDao.GetBadCaseTracingList(ctx, badCaseTracingFilterParams)
	if err != nil {
		return nil, 0, err
	}

	// createdAt 是记录写入时间，feedbackAt 是用户发生真实举报的时间，feedbackAt 字段是后添加的，进行兼容处理
	for _, badCaseTracing := range badCaseTracingList {
		if badCaseTracing.FeedbackAt.Before(badCaseTracing.CreatedAt) {
			badCaseTracing.CreatedAt = badCaseTracing.FeedbackAt
		}
	}

	return badCaseTracingList, int(totalCount), nil
}

func (t *TracingPlatformServiceImpl) IsBadCaseRecordExist(ctx context.Context, traceId string) bool {
	exist, _ := t.badcaseTracingDao.IsBadCaseRecordExist(ctx, traceId)
	return exist
}

func (t *TracingPlatformServiceImpl) GetBadCaseProcess(ctx context.Context, traceId string) (*model.BadcaseTracingProcess, error) {
	badCaseTracingProcess, err := t.badcaseTracingDao.GetBadCaseTracingProcess(ctx, traceId)
	if err != nil {
		return nil, err
	}

	return badCaseTracingProcess, nil
}

func (t *TracingPlatformServiceImpl) AddBadCaseTracingAsync(ctx context.Context, params *model.BadcaseTracingFilterParams) error {
	beginPDate, endPDate := parseTimeAndGetDates(params.RequestTime)
	sql := fmt.Sprintf("SELECT\n  member_id,\n  message_id,\n  request_info,\n  resp_message_id,\n get_json_object(get_json_object(response_info, '$.message'),'$.text') resp_answer, \n  middle_process\n"+
		"FROM\n  logs.aisp_common_tracing\n WHERE\n  p_date BETWEEN '%s' AND '%s'\n  and trace_id='%s'", beginPDate, endPDate, params.TraceId)

	log.Infof(ctx, "start load data from hive traceId: %s", params.TraceId)

	hiveClient := resource.NewHiveClient()
	defer hiveClient.Close()

	cursor := hiveClient.GetCursor()
	cursor.Exec(ctx, "set hive.strict.checks.large.query=false") // 关闭大查询检查
	cursor.Exec(ctx, "set hive.mapred.mode=nonstrict")
	cursor.Exec(ctx, sql)
	if cursor.Err != nil {
		log.Errorf(ctx, "Err:%v", cursor.Err)
		return cursor.Err
	}
	defer cursor.Close()

	doc := proto.Tracing{}
	for cursor.HasMore(ctx) {
		cursor.FetchOne(ctx, &doc.MemberId, &doc.MessageId, &doc.RequestInfo, &doc.RespMessageId, &doc.ResponseInfo, &doc.MiddleProcess)
		break
	}
	log.Infof(ctx, "end load data from hive traceId: %s", params.TraceId)

	if doc.GetMessageId() == "" {
		log.Errorf(ctx, "traceId: %s not found. sql: %s. doc: %s", params.TraceId, sql, util.GetJSONIgnoreError(&doc))
		return fmt.Errorf("traceId: %s not found", params.TraceId)
	}

	var middleProcess proto.TracingMiddleProcess
	if err := jsonpb.UnmarshalString(doc.MiddleProcess, &middleProcess); err != nil {
		log.Errorf(ctx, "jsonpb.UnmarshalString err: %v", err)
		return err
	}

	chatRequest := &proto.ChatRequest{}
	parseErr := util.JSONUnmarshal([]byte(doc.RequestInfo), chatRequest)
	if parseErr != nil {
		log.Errorf(ctx, "JSONUnmarshal err: %v", parseErr)
		return parseErr
	}

	inputBadCaseRecord := &model.BadcaseTracingList{
		MemberId:          util.SafeString2Int64(doc.MemberId, 0),
		ChatScene:         chatRequest.GetType().String(),
		ChatSubScene:      chatRequest.GetHeader().GetTrafficSource().String(),
		RequestMessageId:  doc.MessageId,
		RequestQuery:      chatRequest.GetInfo().GetMessage().GetText(),
		ResponseMessageId: doc.RespMessageId,
		ResponseAnswer:    doc.ResponseInfo,
		TraceId:           params.TraceId,
		FeedbackSource:    params.FeedbackSource,
		CaseType:          params.CaseType,
		CaseDescription:   params.CaseDescription,
		HandlingState:     model.NotYetHandling,
		HandlingMember:    "",
		HandlingResult:    "",
		State:             1,
	}
	inputBadCaseProcess := &model.BadcaseTracingProcess{
		TraceId:     params.TraceId,
		QueryRouter: util.ProtoMarshalEmitDefaults(middleProcess.GetQueryRouter()),
		QueryMerge:  util.ProtoMarshalEmitDefaults(middleProcess.GetQueryMerge()),
		Recalls:     util.GetJSONIgnoreError(middleProcess.GetRecalls()),
		Cards:       util.GetJSONIgnoreError(middleProcess.GetCards()),
		Reranks:     util.GetJSONIgnoreError(middleProcess.GetReranks()),
		Summary:     util.ProtoMarshalEmitDefaults(middleProcess.GetSummary()),
		Securities:  strings.Join(middleProcess.GetSecurity(), ","),
	}

	log.Infof(ctx, "start insert badcase record traceId: %s", params.TraceId)

	// 写入 badcase 记录表
	insertErr := t.badcaseTracingDao.UpsertBadCaseTracingRecord(ctx, inputBadCaseRecord)
	if insertErr != nil {
		log.Errorf(ctx, "UpsertBadCaseTracingRecord err: %v", insertErr)
		return insertErr
	}
	// 写入 badcase 中间过程表
	insertErr = t.badcaseTracingDao.InsertBadCaseTracingProcess(ctx, inputBadCaseProcess)
	if insertErr != nil {
		log.Errorf(ctx, "InsertBadCaseTracingProcess err: %v", insertErr)
		return insertErr
	}

	return nil
}

func (t *TracingPlatformServiceImpl) AddBadCaseTracing(ctx context.Context, params *model.BadcaseTracingFilterParams) error {
	searchResults, err := t.tracingLogService.SearchRucene(ctx, &model.LogRucene{TraceId: params.TraceId})
	if err != nil {
		return err
	}
	if len(searchResults) == 0 {
		return errors.New("未找到记录")
	}
	searchResult := searchResults[0]
	inputBadCaseRecord := &model.BadcaseTracingList{
		MemberId:          searchResult.MemberId,
		ChatScene:         searchResult.Scene,
		ChatSubScene:      "",
		RequestMessageId:  searchResult.MessageId,
		RequestQuery:      searchResult.Query,
		ResponseMessageId: searchResult.RespMessageId,
		ResponseAnswer:    searchResult.GetResponse(),
		TraceId:           params.TraceId,
		FeedbackSource:    params.FeedbackSource,
		CaseType:          params.CaseType,
		CaseDescription:   params.CaseDescription,
		HandlingState:     model.NotYetHandling,
		HandlingMember:    "",
		HandlingResult:    "",
		State:             2,
	}
	// 写入 badcase 记录表
	return t.badcaseTracingDao.UpsertBadCaseTracingRecord(ctx, inputBadCaseRecord)
}

func (t *TracingPlatformServiceImpl) UpdateBadCaseTracing(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error {
	return t.badcaseTracingDao.UpdateBadCaseTracingRecord(ctx, badCaseTracingRecord)
}

func (t *TracingPlatformServiceImpl) UpdateBadCaseToBeResolved(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error {
	return t.badcaseTracingDao.UpdateBadCaseToBeResolved(ctx, badCaseTracingRecord)
}

func (t *TracingPlatformServiceImpl) DeleteBadCaseTracing(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error {
	return t.badcaseTracingDao.DeleteBadCaseTracingRecord(ctx, badCaseTracingRecord)
}

func (t *TracingPlatformServiceImpl) WriteExcel(ctx context.Context, badCaseTracingList []*model.BadcaseTracingList) (*xlsx.File, error) {
	outputFile := xlsx.NewFile()
	sheet1, err := outputFile.AddSheet("badcase记录")
	if err != nil {
		return nil, err
	}

	row := sheet1.AddRow()
	row.AddCell().SetValue("memberId")
	row.AddCell().SetValue("请求messageId")
	row.AddCell().SetValue("用户输入")
	row.AddCell().SetValue("返回messageId")
	row.AddCell().SetValue("模型回答")
	row.AddCell().SetValue("中间过程")
	row.AddCell().SetValue("反馈时间")
	row.AddCell().SetValue("case类型")
	row.AddCell().SetValue("case来源")
	row.AddCell().SetValue("场景")
	row.AddCell().SetValue("二级场景")
	row.AddCell().SetValue("badcase说明")
	row.AddCell().SetValue("具体模块")
	row.AddCell().SetValue("处理状态")
	row.AddCell().SetValue("跟进人")
	row.AddCell().SetValue("备注")
	row.AddCell().SetValue("是否待解决")

	for _, badCaseTracing := range badCaseTracingList {
		middleProcess, _ := t.GetBadCaseProcess(ctx, badCaseTracing.TraceId)

		row = sheet1.AddRow()
		row.AddCell().SetValue(badCaseTracing.MemberId)
		row.AddCell().SetValue(badCaseTracing.RequestMessageId)
		row.AddCell().SetValue(badCaseTracing.RequestQuery)
		row.AddCell().SetValue(badCaseTracing.ResponseMessageId)
		row.AddCell().SetValue(badCaseTracing.ResponseAnswer)
		row.AddCell().SetValue(util.GetJSONIgnoreError(middleProcess))
		row.AddCell().SetValue(util.FormatTime2Datetime(badCaseTracing.CreatedAt))
		row.AddCell().SetValue(badCaseTracing.CaseType)
		row.AddCell().SetValue(badCaseTracing.FeedbackSource)
		row.AddCell().SetValue(badCaseTracing.ChatScene)
		row.AddCell().SetValue(badCaseTracing.ChatSubScene)
		row.AddCell().SetValue(badCaseTracing.CaseDescription)
		row.AddCell().SetValue(badCaseTracing.HandlingModule)
		row.AddCell().SetValue(badCaseTracing.HandlingState)
		row.AddCell().SetValue(badCaseTracing.HandlingMember)
		row.AddCell().SetValue(badCaseTracing.HandlingResult)
		row.AddCell().SetValue(badCaseTracing.ToBeResolved)
	}

	return outputFile, nil
}

func parseTimeAndGetDates(timeStr string) (string, string) {
	// 解析时间字符串
	t, err := time.Parse("2006-01-02 15:04:05", timeStr)
	if err != nil {
		return "", ""
	}

	// 获取当天日期
	today := t.Format("2006-01-02")
	// 获取第二天的日期
	tomorrow := t.AddDate(0, 0, 1).Format("2006-01-02")

	return today, tomorrow
}
