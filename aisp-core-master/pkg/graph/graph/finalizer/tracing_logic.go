package finalizer

import (
	"context"
	"fmt"
	"strings"
	"time"

	"git.in.zhihu.com/go/base/telemetry/statsd"
	"git.in.zhihu.com/go/base/zae"
	"git.in.zhihu.com/go/cafe/config"
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	daoImpl "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc/impl"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/kafka"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/safe_group"
	mapset "github.com/deckarep/golang-set"
	"github.com/samber/lo"
	"github.com/spf13/cast"
)

// TracingRecordLogic
// @logicAuthor: wangran
// @logicInfo: 公共的基类 tracing 算子，需要被子类继承实现 GenRequestInfoFunc 和 GenResponseInfoFunc
// @logicInput: 0 | stream chat开始的时间戳 int64
// @logicInput: 1 | 模型返回首token的时间戳 int64
// @logicInput: 2 | stream chat结束的时间戳 int64
type TracingRecordLogic struct {
	*logic.ConsumerLogicDecorator[entities.RequestContext, entities.User]
	chatEventChainLinkTraceDao dao.ChatEventChainLinkTraceDao
	ruceneRpc                  rpc.RuceneServiceRPC
	qpRpc                      rpc.QueryProfileRpc
	skipRucene                 bool
	kafkaTopic                 string
	GenRequestInfoFunc         func(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string
	GenResponseInfoFunc        func(logCtx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string
}

func NewTracingRecordLogic(name string, config map[string]string) *TracingRecordLogic {
	res := &TracingRecordLogic{
		ConsumerLogicDecorator: logic.NewConsumerLogicDecorator[entities.RequestContext, entities.User](name, config),
	}
	res.RealDoFunc = res.consume
	res.NeedSignal = true
	res.skipRucene = cast.ToBool(config[conf.SkipRuceneTracing.ToConvert()])
	if config[conf.TracingKafkaTopic.ToConvert()] != "" {
		res.kafkaTopic = config[conf.TracingKafkaTopic.ToConvert()]
	} else {
		res.kafkaTopic = string(macro.CommonTracing)
	}
	res.chatEventChainLinkTraceDao = daoImpl.NewChatEventChainLinkTraceDao()
	res.ruceneRpc = rpc.DefaultRuceneServiceRPC
	res.qpRpc = impl.DefaultQpImpl
	return res
}

func (t *TracingRecordLogic) consume(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User]) error {
	span, ctx, logCtx := log.StartChildSpanWithContext(ctx, "finalizer.TracingRecordLogic.consume")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogMemberId(requestCtx.GetBizContext().MemberId()))

	isContextCanceled := false
	if ctx.Err() == context.Canceled {
		isContextCanceled = true
	}

	requestContext := requestCtx.GetBizContext()

	tracing := requestContext.Tracing()
	tracing.RequestInfo = t.GenRequestInfoFunc(requestCtx)
	tracing.ResponseInfo = t.GenResponseInfoFunc(logCtx, requestCtx)
	tracing.RecordTimeMs = time.Now().UnixMilli()
	tracing.TraceId = requestCtx.GetCommonContext().RequestId()
	tracing.SessionId = util.Int64String(requestCtx.GetBizContext().GetSessionId())
	tracing.TrafficSource = requestCtx.GetBizContext().GetTrafficSource().String()

	// 存储用户的最后登录城市
	province, city := user.GetBizUser().UserMeta().GetUserLastProvinceAndCity()
	tracing.ContextTracing = util.ProtoMarshalEmitDefaults(&proto.ContextTracing{
		LastLoginProvince: fmt.Sprintf("%s-%s", province, city),
	})

	securityChan := requestContext.ProcessTracing().SecurityTracing
	promptChan := requestContext.ProcessTracing().Prompt
	llmAnswerChan := requestContext.ProcessTracing().LlmAnswer
	expChan := requestContext.ProcessTracing().Exp
	close(securityChan)
	close(promptChan)
	close(llmAnswerChan)
	close(expChan)

	for item := range securityChan {
		tracing.ProcessTracing.SecurityTracing = append(tracing.ProcessTracing.SecurityTracing, item)
	}
	for item := range promptChan {
		tracing.ProcessTracing.Prompt = append(tracing.ProcessTracing.Prompt, item)
	}
	for item := range llmAnswerChan {
		tracing.ProcessTracing.LlmAnswer = append(tracing.ProcessTracing.LlmAnswer, item)
	}

	// 处理实验数据 实验去重
	for item := range expChan {
		tracing.ProcessTracing.Experiments = append(tracing.ProcessTracing.Experiments, item)
	}
	for domain, expArr := range requestCtx.GetBizContext().GetAbParamAllValue() {
		for expKey, expValue := range expArr {
			expString := fmt.Sprintf("%s,%s,%s", domain, expKey, expValue)
			tracing.ProcessTracing.Experiments = append(tracing.ProcessTracing.Experiments, expString)
		}
	}
	tracing.ProcessTracing.Experiments = lo.Union(tracing.ProcessTracing.Experiments)

	tracing.ProcessTracing.Intention.Intention = requestContext.ProcessTracing().Intention

	var logicConfigMap = make(map[string]string, len(requestContext.GetLogicConfigMap()))
	for logicName, logicConfig := range requestContext.GetLogicConfigMap() {
		logicConfigMap[logicName] = util.GetJSONIgnoreError(logicConfig)
	}
	tracing.ProcessTracing.LogicConfig = logicConfigMap
	tracing.ProcessTracing.Env = zae.DeployStage()

	startMs := time.Now().UnixMilli() - requestCtx.GetCommonContext().Start().Duration().Milliseconds()
	streamChatBeginMs, _ := requestCtx.DataMap().GetInt64(logCtx, t.GetInputName(0))
	firstTokenMs, _ := requestCtx.DataMap().GetInt64(logCtx, t.GetInputName(1))
	streamChatEndMs, _ := requestCtx.DataMap().GetInt64(logCtx, t.GetInputName(2))
	tracing.ProcessTracing.CostTime = map[string]int32{
		"first_token":               int32(max(firstTokenMs-startMs, 0)), // 有些请求不走模型（例如faq），没有首token耗时
		"all":                       int32(requestCtx.GetCommonContext().Start().Duration().Milliseconds()),
		"summary_model_first_token": int32(firstTokenMs - streamChatBeginMs),
		"summary_model_all":         int32(streamChatEndMs - streamChatBeginMs),
	}

	tracing.LogicTracingMap = requestContext.GetLogicTracingMap()

	requestCtx.GetBizContext().GetMiddleProcess().Security = genRuceneSecurityText(ctx, requestContext, tracing.ProcessTracing.SecurityTracing)
	tracing.MiddleProcess = util.ProtoMarshalEmitDefaults(requestCtx.GetBizContext().GetMiddleProcess())

	// 执行 case 模式下不落 tracing
	if requestCtx.GetBizContext().GetRunCaseConfig().IsOpen {
		return nil
	}

	newCtx, cancel := context.WithTimeout(util.WithoutCancel(ctx), 6*time.Second)
	defer cancel()

	// 存储当前agent trace 到tidb中 用于快速排查问题
	if chatEvent := requestCtx.GetBizContext().GetChatEvent(); chatEvent != nil {
		traceJson, traceErr := chatEvent.GetAllEventData().GetTraceJson()
		if traceErr == nil {
			tracing.EventChainTracing = traceJson
			safe_group.SafeGo(func() error {
				dto := &model.ChatEventChainLinkTrace{
					TraceId:            tracing.TraceId,
					ChainLinkTraceJson: tracing.EventChainTracing,
				}
				// apollo 配置白名单存储 MiddleProcess
				middleProcessWhiteList := config.GetString("trace.middle_process.whitelist", "")
				if strings.Contains(middleProcessWhiteList, cast.ToString(requestCtx.GetBizContext().MemberId())) {
					dto.MiddleProcess = tracing.MiddleProcess
				}
				_, err := t.chatEventChainLinkTraceDao.SaveTrace(newCtx, dto)
				return err
			}, "SaveAgentChainLinkTrace")
		}
	}

	// 发送 kafka 消息，由 datasync 进行 kafka->hive
	kafkaErr := t.sendKafka(newCtx, tracing, isContextCanceled)
	// 落 rucene，用于 tracing 平台查询
	var ruceneErr error
	if !t.skipRucene {
		ruceneErr = t.saveRucene(newCtx, tracing, requestCtx)
	}

	if kafkaErr != nil {
		return kafkaErr
	} else {
		return ruceneErr
	}
}

func (t *TracingRecordLogic) sendKafka(ctx context.Context, tracing *proto.Tracing, isContextCanceled bool) error {
	// pb 序列化，忽略 omitempty，全部输出
	if tracing.GetProcessTracing() != nil {
		tracing.GetProcessTracing().IsUserCancelled = isContextCanceled
	}
	tracingJson := util.ProtoMarshalEmitDefaults(tracing)

	producer, err := kafka.GetProducer(context.Background(), t.kafkaTopic)
	if err != nil {
		log.WithError(ctx, err).Error(ctx, "get producer failed:%s", t.kafkaTopic)
		return err
	}

	return producer.AsyncSend(ctx, &kafka.ProducerMessage{
		Value: []byte(tracingJson),
	})
}

var originProcessStatsFmt = macro.OriginCommonStatsPrefix + ".%s.%s.count"
var processStatsFmt = macro.CommonStatsPrefix + ".%s.%s.count"

func (t *TracingRecordLogic) saveRucene(ctx context.Context, tracing *proto.Tracing, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) error {

	requestContext := requestCtx.GetBizContext()

	var responseTexts = make([]string, 0, len(requestContext.ResponseItemList()))
	for _, item := range requestContext.ResponseItemList() {
		responseTexts = append(responseTexts, item.Text)
	}

	query := tracing.GetQuery()
	responseText := strings.Join(responseTexts, " ")

	requestTimeMs := requestContext.RequestMessage().GetTimestampMs()
	if !util.IsMillisecond(requestTimeMs) {
		requestTimeMs = requestTimeMs * 1000
	}

	ruceneDoc := &model.LogRucene{
		Id:            genRuceneDocId(requestContext),
		MemberId:      requestContext.MemberId(),
		Scene:         requestContext.GetBizType(),
		GraphName:     requestContext.Scenes(),
		SessionId:     util.Int64String(requestContext.GetSessionId()),
		RequestTimeMs: requestTimeMs,
		MessageId:     tracing.GetMessageId(),
		Query:         query,
		QuerySeg: model.SegmentInfo{
			Words: t.getSegment(ctx, query),
			Raw:   query,
			Store: true,
		},
		ResponseTimeMs: time.Now().UnixMilli(),
		RespMessageId:  tracing.GetRespMessageId(),
		Response:       responseTexts,
		ResponseSeg: model.SegmentInfo{
			Words: t.getSegment(ctx, responseText),
			Raw:   responseText,
			Store: true,
		},
		Security:      requestCtx.GetBizContext().GetMiddleProcess().Security,
		AuthorId:      requestContext.AuthorInfo().GetMemberId(),
		TraceId:       tracing.GetTraceId(),
		ClientSource:  requestCtx.GetBizContext().GetClientSource().String(),
		TrafficSource: requestCtx.GetBizContext().GetTrafficSource().String(),
		RequestInfo:   tracing.GetRequestInfo(),
		ResponseInfo:  tracing.GetResponseInfo(),
		AppName:       zae.App(),
		ServiceName:   zae.Service(),
	}

	ruceneHost := config.MustGetString(macro.BaiduRuceneProxyConfigName)

	return t.ruceneRpc.AddWithRetry(ctx, ruceneHost, model.Path, model.Index, ruceneDoc, "")
}

func (t *TracingRecordLogic) getSegment(ctx context.Context, text string) []*model.Word {
	var result []*model.Word
	response := t.qpRpc.GetQueryProfile(ctx, text)
	if response == nil {
		return result
	}

	segWords := response.GetQueryProfile().GetSegmentInfo().GetWords()
	for _, item := range segWords {
		if item.GrainType == 1 {
			result = append(result, &model.Word{
				Value:  item.Word,
				Begin:  item.PositionBegin,
				Length: item.Length,
			})
		}
	}

	return result
}

var securityFailedStages = mapset.NewSet(
	proto.BusinessStage_QUERY,
	proto.BusinessStage_QUERY_MERGE,
	proto.BusinessStage_GENERATION,
	proto.BusinessStage_GENERATION_STREAM,
)

func genRuceneSecurityText(ctx context.Context, requestContext *entities.RequestContext, securityTracing []*proto.SecurityTracing) []string {
	var securityText = make([]string, 0)
	securityTextUniqueMap := map[string]bool{}
	for _, each := range securityTracing {
		if each.GetDoSecurityReview() && !each.GetIsPass() && !securityTextUniqueMap[macro.SecurityReviewFailed] {
			// 仅针对拒绝回答的，给到安全拦截文案。但是所有调用安全失败的（包括召回和相关问题），都进行打点监控
			if securityFailedStages.Contains(each.GetStage()) {
				securityText = append(securityText, macro.SecurityReviewFailed)
				securityTextUniqueMap[macro.SecurityReviewFailed] = true
			}
			// 新
			util.Increment(ctx, processStatsFmt, "security_review", "failed")
			// 老
			statsd.Increment(fmt.Sprintf(originProcessStatsFmt, requestContext.Scenes(), "security_review", "failed"))
		}
		if each.GetRedLine() != "" && !securityTextUniqueMap[macro.Redline] {
			securityText = append(securityText, macro.Redline)
			securityTextUniqueMap[macro.Redline] = true
			// 新
			util.Increment(ctx, processStatsFmt, "red_line", "hit")
			// 老
			statsd.Increment(fmt.Sprintf(originProcessStatsFmt, requestContext.Scenes(), "red_line", "hit"))
		}
		if each.GetFaq() != "" && !securityTextUniqueMap[macro.Faq] {
			securityText = append(securityText, macro.Faq)
			securityTextUniqueMap[macro.Faq] = true
			// 新
			util.Increment(ctx, processStatsFmt, "faq", "hit")
			// 老
			statsd.Increment(fmt.Sprintf(originProcessStatsFmt, requestContext.Scenes(), "faq", "hit"))
		}
		if each.GetKnowledgeEnhance() != "" && !securityTextUniqueMap[macro.KnowledgeEnhance] {
			securityText = append(securityText, macro.KnowledgeEnhance)
			securityTextUniqueMap[macro.KnowledgeEnhance] = true
			// 新
			util.Increment(ctx, processStatsFmt, "knowledge", "hit")
			// 老
			statsd.Increment(fmt.Sprintf(originProcessStatsFmt, requestContext.Scenes(), "knowledge", "hit"))
		}
	}
	// 新
	util.Increment(ctx, processStatsFmt, "security", "all")
	// 老
	statsd.Increment(fmt.Sprintf(originProcessStatsFmt, requestContext.Scenes(), "security", "all"))

	return securityText
}

func genRuceneDocId(requestContext *entities.RequestContext) string {
	return fmt.Sprintf("%s-%d-%s", requestContext.Scenes(), requestContext.GetSessionId(), requestContext.MessageId())
}
