package rpc

import "context"

type QuarkSearchRPC interface {
	Search(ctx context.Context, query string, topK int32, traceId string) ([]*OutSiteSearchRecallAnswerResult, error)
}
