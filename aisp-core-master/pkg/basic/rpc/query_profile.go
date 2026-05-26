package rpc

import (
	"context"

	query_profile "git.in.zhihu.com/pb-go/search-proto/query-profile"
)

type QueryProfileWithField = query_profile.Field
type QueryProfileResponse = query_profile.QpResponse

type QueryProfileConfig struct {
	IncludeField []QueryProfileWithField
	ExcludeField []QueryProfileWithField
}

type QueryProfileRpc interface {
	GetQueryProfile(ctx context.Context, query string) *QueryProfileResponse
	GetQueryKeyWords(ctx context.Context, query string) []*query_profile.QpTerm
}
