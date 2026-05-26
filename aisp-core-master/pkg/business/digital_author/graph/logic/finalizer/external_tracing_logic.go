package finalizer

import (
	"context"
	"encoding/json"
	"time"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/business/digital_author/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/kafka"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
	"github.com/samber/lo"
)

type ExternalTracingRecordLogic struct {
	*framework.ConsumeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewTracingRecordLogic(name string, config map[string]string) *ExternalTracingRecordLogic {
	res := &ExternalTracingRecordLogic{
		ConsumeLogic: framework.NewConsumeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.ConsumeFunc = res.consume
	res.NeedSignal = true
	return res
}

func (t *ExternalTracingRecordLogic) consume(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) error {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "finalizer.ExternalTracingRecordLogic.consume")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user))

	requestContext := requestCtx.GetBizContext()

	tracing := &model.TracingKafkaMsg{
		MessageId:       requestContext.RespMessageId(),
		Intention:       requestContext.GetIntention().IntentionType.String(),
		TaskId:          requestCtx.GetBizContext().ProductContext().(*model.DigitalAuthorContext).HitTask().GetId(),
		RecallKnowledge: requestContext.ProductContext().(*model.DigitalAuthorContext).RecallKnowledge(),
		QueryMerge:      requestContext.GetQueryMerge().Text,
	}
	// 处理安全审核内容
	securityChan := requestContext.ProcessTracing().SecurityTracing
	close(securityChan)
	for item := range securityChan {
		tracing.Security = getSecurityCode(item)
	}

	tracingJson := lo.Must(json.Marshal(tracing))

	producer, err := kafka.GetProducer(context.Background(), string(macro.DigitalAuthorBizTracing))
	if err != nil {
		log.WithError(ctx, err).Error(ctx, "get producer failed:%s", macro.DigitalAuthorBizTracing)
		return err
	}

	newCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	err = producer.AsyncSend(newCtx, &kafka.ProducerMessage{
		Value: tracingJson,
	})

	log.Infof(ctx, "tracing:%s", tracingJson)

	return err
}

func getSecurityCode(security *proto.SecurityTracing) model.SecurityCode {
	if security.GetStage() == proto.BusinessStage_QUERY ||
		security.GetStage() == proto.BusinessStage_QUERY_MERGE ||
		security.GetStage() == proto.BusinessStage_GENERATION ||
		security.GetStage() == proto.BusinessStage_GENERATION_STREAM {
		if security.RedLine != "" {
			return model.RedLineCode
		}
		if !security.GetIsPass() {
			return model.ReviewFailedCode
		}
	}
	return model.NormalCode
}
