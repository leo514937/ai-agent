package user_feedback

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/resource"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/golang/protobuf/jsonpb"
)

var badCaseTracingDao = daoImpl.DefaultBadCaseTracingDaoImpl

const statsFmt = "aisp-core.crontab.badcase.err"

func SyncUserFeedBack() {
	ctx := context.TODO()

	pDate := time.Now().AddDate(0, 0, -1).Format("2006-01-02")

	sql := fmt.Sprintf(`
SELECT
  feedback.feedback_content,
  feedback.feedback_id_str,
  tracing.member_id,
  tracing.message_id,
  request_info,
  resp_message_id,
  get_json_object(
    get_json_object(response_info, '$.message'),
    '$.text'
  ) resp_answer,
  middle_process,
  trace_id,
  created_at
FROM
  (
    SELECT
      member_id,
      message_id,
      feedback_content,
      feedback_id_str,
      created_at
    FROM
      dw_community.src_ob_ai_ingress_user_feedback
    WHERE
      SUBSTR(created_at, 0, 10) >= '%s'
  ) feedback
  JOIN logs.aisp_common_tracing tracing ON tracing.p_date >= '%s'
  AND CAST(feedback.message_id AS STRING) = tracing.resp_message_id
  AND CAST(feedback.member_id AS STRING) = tracing.member_id`, pDate, pDate)

	log.Infof(ctx, "start read user feedback badCase pDate: %s", pDate)

	hiveClient := resource.NewHiveClient()
	defer hiveClient.Close()

	cursor := hiveClient.GetCursor()
	cursor.Exec(ctx, "set hive.mapred.mode=nonstrict")
	cursor.Exec(ctx, sql)
	if cursor.Err != nil {
		log.Errorf(ctx, "Err:%v", cursor.Err)
		// 错误直接退出，定时任务配置重试次数
		os.Exit(1)
		return
	}
	defer cursor.Close()

	for cursor.HasMore(ctx) {
		doc := proto.Tracing{}
		var feedbackContent, feedbackIdStr, feedbackAt string
		cursor.FetchOne(ctx, &feedbackContent, &feedbackIdStr, &doc.MemberId, &doc.MessageId, &doc.RequestInfo, &doc.RespMessageId, &doc.ResponseInfo, &doc.MiddleProcess, &doc.TraceId, &feedbackAt)
		if doc.GetMessageId() == "" {
			log.Errorf(ctx, "empty doc: %s", util.GetJSONIgnoreError(&doc))
			statsd.Increment(statsFmt)
			continue
		}

		var middleProcess proto.TracingMiddleProcess
		if err := jsonpb.UnmarshalString(doc.MiddleProcess, &middleProcess); err != nil {
			log.Errorf(ctx, "jsonpb.UnmarshalString err: %v", err)
			statsd.Increment(statsFmt)
			continue
		}

		chatRequest := &proto.ChatRequest{}
		parseErr := util.JSONUnmarshal([]byte(doc.RequestInfo), chatRequest)
		if parseErr != nil {
			log.Errorf(ctx, "JSONUnmarshal err: %v", parseErr)
			statsd.Increment(statsFmt)
			continue
		}

		if feedbackIdStr != "其他" {
			feedbackContent = ""
		}

		log.Infof(ctx, "start insert badcase record traceId: %s", doc.TraceId)

		feedbackTime, err := time.Parse("2006-01-02 15:04:05", feedbackAt)
		if err != nil {
			feedbackTime = time.Now()
		}

		inputBadCaseRecord := &model.BadcaseTracingList{
			MemberId:          util.SafeString2Int64(doc.MemberId, 0),
			ChatScene:         chatRequest.GetType().String(),
			ChatSubScene:      chatRequest.GetHeader().GetTrafficSource().String(),
			RequestMessageId:  doc.MessageId,
			RequestQuery:      chatRequest.GetInfo().GetMessage().GetText(),
			ResponseMessageId: doc.RespMessageId,
			ResponseAnswer:    doc.ResponseInfo,
			TraceId:           doc.TraceId,
			FeedbackSource:    "普通用户反馈",
			CaseType:          feedbackIdStr,
			CaseDescription:   feedbackContent,
			HandlingState:     model.NotYetHandling,
			HandlingMember:    "",
			HandlingResult:    "",
			FeedbackAt:        feedbackTime,
			State:             1,
		}
		inputBadCaseProcess := &model.BadcaseTracingProcess{
			TraceId:     doc.TraceId,
			QueryRouter: util.ProtoMarshalEmitDefaults(middleProcess.GetQueryRouter()),
			QueryMerge:  util.ProtoMarshalEmitDefaults(middleProcess.GetQueryMerge()),
			Recalls:     util.GetJSONIgnoreError(middleProcess.GetRecalls()),
			Cards:       util.GetJSONIgnoreError(middleProcess.GetCards()),
			Reranks:     util.GetJSONIgnoreError(middleProcess.GetReranks()),
			Summary:     util.ProtoMarshalEmitDefaults(middleProcess.GetSummary()),
			Securities:  strings.Join(middleProcess.GetSecurity(), ","),
		}
		// 写入 badcase 记录表
		insertErr := badCaseTracingDao.UpsertBadCaseTracingRecord(ctx, inputBadCaseRecord)
		if insertErr != nil {
			log.Errorf(ctx, "UpsertBadCaseTracingRecord err: %v", insertErr)
			statsd.Increment(statsFmt)
			continue
		}
		// 写入 badcase 中间过程表
		insertErr = badCaseTracingDao.InsertBadCaseTracingProcess(ctx, inputBadCaseProcess)
		if insertErr != nil {
			log.Errorf(ctx, "InsertBadCaseTracingProcess err: %v", insertErr)
			statsd.Increment(statsFmt)
			continue
		}

		log.Infof(ctx, "end insert badcase record traceId: %s", doc.TraceId)
	}

	log.Infof(ctx, "end read user feedback badCase pDate: %s", pDate)
}
