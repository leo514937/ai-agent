package rpc

import (
	"context"

	"git.in.zhihu.com/one-rpc-go/thrift-content_prod/content_prod_thrift/content"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/core/model"
)

type CurlRespInfo = content.CurlRespInfo

type ContentProdRPC interface {
	BatchCurlContentByUrl(ctx context.Context, urls []string) map[string]*CurlRespInfo
	BatchGetContent(ctx context.Context, items []model.Content, withFields *content.WithFieds) map[model.Content]*content.Content
}
