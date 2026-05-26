package request

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_biz/aisp_core_translate"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/grpc"
)

func NewTranslateHTMLRequest(
	host string,
) *TranslateHTMLRequest {
	qMsg := &TranslateHTMLRequest{}
	client, ctx := getClient(host)
	qMsg.host = host
	qMsg.ctx = ctx
	qMsg.client = client
	return qMsg
}

// getClient 获取 client
func getClient(host string) (proto.AispTranslateServiceClient, context.Context) {
	ctx := context.Background()
	conn, err := grpc.DialContext(ctx, host)
	if err != nil {
		panic(err)
	}

	serviceClient := proto.NewAispTranslateServiceClient(conn)
	return serviceClient, ctx
}
