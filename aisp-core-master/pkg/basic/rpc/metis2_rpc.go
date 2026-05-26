package rpc

import (
	"context"
)

type Metis2Rpc interface {
	GetQuestionAnswerIds(ctx context.Context, questionId int64, topK int32) []int64
	ConcurrentGetQuestionAnswerIds(ctx context.Context, questionIds []int64, topK int32, concurrency int) map[int64][]int64
}
