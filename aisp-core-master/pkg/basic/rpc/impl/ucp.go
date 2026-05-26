package impl

import (
	"context"
	"time"

	"git.in.zhihu.com/pb-go/zai-proto/ai/common"
	"git.in.zhihu.com/pb-go/zai-proto/ai/content_grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/rpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util/failsafe"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
)

type UcpGrpcImpl struct {
	timeout time.Duration
	client  content_grpc.PluginServiceClient
}

var DefaultUcpGrpcImpl rpc.UcpGRPC

func init() {
	DefaultUcpGrpcImpl = NewUcpGrpcImpl()
}

func NewUcpGrpcImpl() *UcpGrpcImpl {
	conn, err := grpc.DialContext(context.Background(), "bayes-query-unified")
	if err != nil {
		log.Errorf(context.Background(), "dial bayes-query-unified err: %+v", err)

		panic(err)
	}

	return &UcpGrpcImpl{
		client:  content_grpc.NewPluginServiceClient(conn),
		timeout: 1000 * time.Millisecond,
	}
}

func (u *UcpGrpcImpl) BatchGetBayesTagInfos(ctx context.Context, queries []string) [][]*common.TagInfo {
	var result [][]*common.TagInfo

	runFunc := func(ctx context.Context) (err error) {
		newCtx, cancel := context.WithTimeout(ctx, u.timeout)
		defer cancel()

		var plugInRequests []*content_grpc.PluginRequest
		for _, query := range queries {
			plugInRequests = append(plugInRequests, &content_grpc.PluginRequest{
				Content: query,
			})
		}

		request := &content_grpc.PluginRequests{Request: plugInRequests}

		response, err := u.client.BatchGet(newCtx, request)

		if err == nil && response != nil && len(response.Response) == len(queries) {
			for _, resp := range response.Response {
				result = append(result, resp.GetItem())
			}
		}
		return err
	}
	failsafe.DefaultRPCCircuitBreakerFailSafe(ctx, runFunc)

	return result
}

var _ rpc.UcpGRPC = (*UcpGrpcImpl)(nil)
