package grpc

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph"
	_ "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/resources"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"google.golang.org/grpc"
)

var RegisterAispRecallServiceServer = func(registrar grpc.ServiceRegistrar) {
	proto.RegisterAispRecallServiceServer(registrar, NewAispRecallService())
}

type AispRecallService struct {
	proto.UnimplementedAispRecallServiceServer
	serviceName   string
	recallService *sub_graph.RecallService
}

var _ proto.AispRecallServiceServer = &AispRecallService{}

func NewAispRecallService() *AispRecallService {
	return &AispRecallService{
		serviceName:   "AispRecallService",
		recallService: sub_graph.NewRecallService(),
	}
}

func (a *AispRecallService) GetZhidaRecall(ctx context.Context, request *proto.ZhidaRecallRequest) (*proto.ZhidaRecallResponse, error) {
	logger := log.WithField(ctx, "StreamChat.Request", request)
	logger.Infof(ctx, "Start, RequestParams:%v", util.GetJSONIgnoreError(request))

	recallItems, err := a.recallService.Recall(ctx, request)

	if err != nil {
		logger.WithError(ctx, err).Error(ctx, "RunGraph failed")
		return nil, err
	}

	respRecallItems := make([]*proto.ZhidaRecallItem, 0, len(recallItems))

	for _, item := range recallItems {
		respRecallItems = append(respRecallItems, item.ToRecallItem())
	}

	return &proto.ZhidaRecallResponse{
		RecallItems: respRecallItems,
	}, nil
}
