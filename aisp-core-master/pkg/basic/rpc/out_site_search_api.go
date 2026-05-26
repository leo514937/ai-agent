package rpc

import "context"

type OutSiteSearchApi interface {
	Search(ctx context.Context, query string, topK int32) ([]*OutSiteSearchRecallAnswerResult, error)
}
