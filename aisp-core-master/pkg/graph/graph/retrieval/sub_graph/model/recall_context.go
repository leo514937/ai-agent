package model

import (
	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
)

const RecallProductName = "recall"

type RecallContext struct {
	requestInfo *proto.ZhidaRecallRequest
}

func (d *RecallContext) GetProductName() string {
	return RecallProductName
}

func (d *RecallContext) RequestInfo() *proto.ZhidaRecallRequest {
	return d.requestInfo
}

func NewRecallContext(request *proto.ZhidaRecallRequest) *RecallContext {
	return &RecallContext{
		requestInfo: request,
	}
}

var _ entities.ProductContext = (*RecallContext)(nil)
