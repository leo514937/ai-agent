package budget

import "context"

type Service interface {
	// HasBudget 判断是否有足够的预算
	HasBudget(ctx context.Context, tenantID int64, taskID int64) (bool, error)
	// TriggerBilling 会触发(异步)计费
	TriggerBilling(ctx context.Context, tenantID, taskID, dialogueID int64, modelName string, inputTokenCount, outputTokenCount int64) error
}

var DefaultService Service
