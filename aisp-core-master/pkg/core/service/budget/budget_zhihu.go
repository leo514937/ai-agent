package budget

import (
	"context"
	"encoding/json"
	"time"

	"git.in.zhihu.com/go/base/grpc"
	"git.in.zhihu.com/go/base/zae"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/dao"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/kafka"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"github.com/samber/lo"
)

type BillingMessage struct {
	CallerApp             string              `json:"caller_app"`
	CallerUnit            string              `json:"caller_unit"`
	ServiceApp            string              `json:"service_app"`
	ServiceUnit           string              `json:"service_unit"`
	SkuName               string              `json:"sku_name"`
	InvocationID          string              `json:"invocation_id"`
	InvocationTimestampMs int64               `json:"invocation_timestamp_ms"`
	Usage                 BillingMessageUsage `json:"usage"`
}

type BillingMessageUsage struct {
	InputTokenCount  int64 `json:"input_token_count"`
	OutputTokenCount int64 `json:"output_token_count"`
}

type ZhihuService struct {
	taskDAO dao.TaskDAO
}

func (z *ZhihuService) HasBudget(ctx context.Context, tenantID int64, taskID int64) (bool, error) {
	return true, nil
}

func (z *ZhihuService) TriggerBilling(ctx context.Context, tenantID, taskID, dialogueID int64, modelName string, inputTokenCount, outputTokenCount int64) error {
	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "budget.Service.TriggerBilling",

		"tenant_id":   tenantID,
		"task_id":     taskID,
		"dialogue_id": dialogueID,
		"input":       inputTokenCount,
		"output":      outputTokenCount,
	})

	producer, err := kafka.GetProducer(ctx, macro.BillingTopic)
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "get producer failed")
		return err
	}

	caller := grpc.CallerFromContext(ctx)
	err = producer.AsyncSend(ctx, &kafka.ProducerMessage{
		Value: lo.Must(json.Marshal(&BillingMessage{
			CallerApp:             caller.App,
			CallerUnit:            caller.Service,
			ServiceApp:            zae.App(),
			ServiceUnit:           zae.Service(),
			SkuName:               modelName,
			InvocationID:          util.Int64ToStr(dialogueID),
			InvocationTimestampMs: time.Now().UnixMilli(),
			Usage: BillingMessageUsage{
				InputTokenCount:  inputTokenCount,
				OutputTokenCount: outputTokenCount,
			},
		})),
	})
	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "send message failed")
		return err
	}
	return nil
}

func NewZhihuService() *ZhihuService {
	return &ZhihuService{
		taskDAO: dao.DefaultTaskDAO,
	}
}

func init() {
	DefaultService = NewZhihuService()
}
