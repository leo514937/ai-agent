package rpc

import (
	"context"
)

type BingClientRPC interface {
	BingSearch(ctx context.Context, q string, topK int32, extParams map[string]string) ([]*OutSiteSearchRecallAnswerResult, error)
}
