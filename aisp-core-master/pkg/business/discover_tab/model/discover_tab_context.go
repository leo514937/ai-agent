package model

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
)

const DiscoverTabProductName = "discover_tab"

type DiscoverTabContext struct {
	requestInfo *proto.ChatRequest
}

func (d *DiscoverTabContext) GetProductName() string {
	return DiscoverTabProductName
}

func (d *DiscoverTabContext) RequestInfo() *proto.ChatRequest {
	return d.requestInfo
}

func NewDiscoverTabContext(request *proto.ChatRequest) *DiscoverTabContext {
	return &DiscoverTabContext{
		requestInfo: request,
	}
}

var _ entities.ProductContext = (*DiscoverTabContext)(nil) // 检测是否实现全部方法
