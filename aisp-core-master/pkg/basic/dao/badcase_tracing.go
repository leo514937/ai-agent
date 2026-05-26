package dao

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type BadCaseTracingDao interface {
	GetBadCaseTracingList(ctx context.Context, filterParam *model.BadcaseTracingFilterParams) ([]*model.BadcaseTracingList, int64, error)
	GetBadCaseTracingProcess(ctx context.Context, tracingId string) (*model.BadcaseTracingProcess, error)
	UpsertBadCaseTracingRecord(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error
	IsBadCaseRecordExist(ctx context.Context, traceId string) (bool, int64)
	InsertBadCaseTracingProcess(ctx context.Context, badCaseTracingProcess *model.BadcaseTracingProcess) error
	UpdateBadCaseTracingRecord(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error
	DeleteBadCaseTracingRecord(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error
	UpdateBadCaseToBeResolved(ctx context.Context, badCaseTracingRecord *model.BadcaseTracingList) error
}
