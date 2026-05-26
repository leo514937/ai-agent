package sub_graph

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/config/stage_handler"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	graph_macro "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph/api"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph/model"
	recall_model "git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/retrieval/sub_graph/model"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	zagMap "git.in.zhihu.com/zrec/zag-driver/pkg/core/driver"
	zagDriverEntities "git.in.zhihu.com/zrec/zag-driver/pkg/core/driver/entities"
	"git.in.zhihu.com/zrec/zag-driver/pkg/framework/constant"
	"git.in.zhihu.com/zrec/zag-driver/pkg/framework/tools"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame/consts"
	zagHandler "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy"
	strategyEntities "git.in.zhihu.com/zrec/zrec-framework/pkg/core/strategy/entities"
)

type RecallService struct {
	zagDriver *zagMap.ZagDriverImpl[data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]]
}

func NewRecallService() *RecallService {
	graph := api.ZhiDaV2RecallGraph[entities.RequestContext, entities.User, entities.Item](proto.ChatType_ZHIDA_V2.String())
	//逻辑图 >>>物理图
	driverConfig := zagDriverEntities.NewDriverConfig() //物理图执行器配置
	driverConfig.SetMaxConcurrency(1000000)
	driverConfig.SetUsePool(false)
	driverConfig.SetOpenSamplingLog(true)
	driverConfig.SetSamplingRate(100)

	zagDriver := zagHandler.GraphToZagDriver[entities.RequestContext, entities.User, entities.Item](graph, driverConfig)
	zagDriver.ToString(graph_constant.ApiRecall)

	return &RecallService{
		zagDriver: zagDriver,
	}
}

func (r *RecallService) RunGraph(ctx context.Context, bizRequestContext *entities.RequestContext) ([]*entities.Item, error) {
	config := strategyEntities.NewRuntimeConfig[entities.RequestContext, entities.User, entities.Item](macro.ResponseNode, graph_constant.ApiRecall+"."+bizRequestContext.GetBizType(), 10*1000)

	scenes := graph_constant.ApiRecall + "." + bizRequestContext.GetBizType()
	memberID := bizRequestContext.MemberId()
	requestInfo := bizRequestContext.ProductContext().(*model.RecallContext).RequestInfo()
	requestId := requestInfo.GetRecallExtInfo().GetRequestId()
	if requestId == "" {
		if ctx.Value(constant.TraceIdKey) != nil {
			requestId = ctx.Value(constant.TraceIdKey).(string)
		} else {
			requestId = tools.GetNextId()
		}
	}

	// 初始化 zag framework 层自动添加的框架算子元信息
	requestContext := data_frame.NewRequestContext[entities.RequestContext, entities.User, entities.Item]()
	requestContext.GetCommonContext().SetServiceName(scenes)
	requestContext.GetCommonContext().SetRequestId(requestId)
	requestContext.GetCommonContext().SetLimit(1)
	requestContext.SetBizContext(bizRequestContext)

	user := requestContext.GetCommonContext().GetLogicData(consts.User_key).(*data_frame.UserData[entities.User])
	bizUser := entities.NewUser(user)
	bizUser.SetMemberId(bizRequestContext.MemberId())
	user.SetBizUser(bizUser)

	requestContext.DataMap().SetString(ctx, graph_macro.ZagKeyIntention, requestInfo.GetRecallExtInfo().GetIntention())

	config.AddNodeListener(macro.ResponseNode, func(requestContext *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) {
		log.Infof(ctx, "请求正常结束！requestContext.FlowResponse size: %d", len(requestContext.GetBizContext().ResponseItemList()))
	})

	ctx = log.ContextWithScene(ctx, scenes)
	ctx = log.ContextWithMemberID(ctx, memberID)
	ctx = log.ContextWithAB(ctx, bizRequestContext.GetAbParamValueStrSlice())
	ctx = log.ContextWithClientSource(ctx, bizRequestContext.RequestHeader().GetClientSource())
	ctx = log.ContextWithTrafficSource(ctx, bizRequestContext.RequestHeader().GetTrafficSource())
	ctx = log.ContextWithTrafficReference(ctx, bizRequestContext.RequestHeader().GetTrafficReference())

	err := zagHandler.GraphRun[entities.RequestContext, entities.User, entities.Item](ctx, requestContext, r.zagDriver, config)
	if err != nil {
		log.WithError(ctx, err).Error(ctx, "GraphRun error")
		return nil, err
	}

	return requestContext.GetBizContext().ResponseItemList(), nil
}

func (r *RecallService) Recall(ctx context.Context, request *proto.ZhidaRecallRequest) ([]*entities.Item, error) {
	graphStageLogicConfig, _ := stage_handler.GetGraphStageConfig(stage_handler.GraphLogicConfigNameByRecall)
	bizRequestContext := entities.NewRequestContextFromRecallRequest(request, graphStageLogicConfig, recall_model.NewRecallContext(request))
	recallItems, err := r.RunGraph(ctx, bizRequestContext)

	return recallItems, err
}
