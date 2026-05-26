package rpc

import (
	"context"
)

type BoChaClientHTTP interface {
	Search(ctx context.Context, query string, topK int32, freshness BoChaFreshness, isSummary bool) ([]*OutSiteSearchRecallAnswerResult, error)
}

type BoChaFreshness string

const (
	BoChaFreshnessOneDay   BoChaFreshness = "oneDay"
	BoChaFreshnessOneWeek  BoChaFreshness = "oneWeek"
	BoChaFreshnessOneMonth BoChaFreshness = "oneMonth"
	BoChaFreshnessOneYear  BoChaFreshness = "oneYear"
	BoChaFreshnessNoLimit  BoChaFreshness = "noLimit"
)
