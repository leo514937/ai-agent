package impl

import (
	"context"
	"time"

	query_profile "git.in.zhihu.com/pb-go/search-proto/query-profile"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/tools/grpc"
)

type QueryProfileRpcImpl struct {
	timeout   time.Duration
	rpcClient query_profile.QpServiceClient
}

var DefaultQpImpl rpc.QueryProfileRpc

func init() {
	DefaultQpImpl = NewQueryProfileRpcImpl()
}

var _ rpc.QueryProfileRpc = (*QueryProfileRpcImpl)(nil)

func NewQueryProfileRpcImpl() *QueryProfileRpcImpl {
	conn := grpc.Build(context.Background(), "qp-algo")
	return &QueryProfileRpcImpl{
		timeout:   1000 * time.Millisecond,
		rpcClient: query_profile.NewQpServiceClient(conn),
	}
}

func (q *QueryProfileRpcImpl) GetQueryProfile(ctx context.Context, query string) *rpc.QueryProfileResponse {
	var resp *rpc.QueryProfileResponse
	runFunc := func(ctx context.Context) error {
		newCtx, cancel := context.WithTimeout(context.Background(), q.timeout)
		defer cancel()
		request := &query_profile.QpRequest{
			RawQuery: query,
			IncludeFields: []rpc.QueryProfileWithField{
				query_profile.Field_SEGMENT,
			},
			ExcludeFields: []query_profile.Field{
				query_profile.Field_CORRECT,
				query_profile.Field_REGENCY,
			},
		}
		response, err := q.rpcClient.GetQp(newCtx, request)
		if err == nil && response != nil {
			resp = response
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return resp
}

func (q *QueryProfileRpcImpl) GetQueryKeyWords(ctx context.Context, query string) []*query_profile.QpTerm {
	var resp []*query_profile.QpTerm
	runFunc := func(ctx context.Context) error {
		newCtx, cancel := context.WithTimeout(context.Background(), q.timeout)
		defer cancel()
		request := &query_profile.QpRequest{
			RawQuery: query,
			IncludeFields: []rpc.QueryProfileWithField{
				query_profile.Field_QU_TERMS,
			},
			ExcludeFields: []query_profile.Field{
				query_profile.Field_CORRECT,
				query_profile.Field_REGENCY,
			},
		}
		response, err := q.rpcClient.GetQp(newCtx, request)
		if err == nil && response != nil {
			resp = response.GetQueryProfile().GetQuTerms()
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)
	return resp
}
