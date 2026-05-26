package sub_graph

import (
	"context"
	"fmt"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities/graph_constant"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/router/sub_graph/api"
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

type IGraphService interface {
	Handle(ctx context.Context, requestContext *entities.RequestContext) ([]*entities.Item, error)
}

type DirectChatSubService struct {
	zagDriver *zagMap.ZagDriverImpl[data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]]
}

func NewDirectChatSubService() IGraphService {
	graph := api.DirectChatSubGraph[entities.RequestContext, entities.User, entities.Item]()
	//逻辑图 >>>物理图
	driverConfig := zagDriverEntities.NewDriverConfig() //物理图执行器配置
	driverConfig.SetMaxConcurrency(1000000)
	driverConfig.SetUsePool(false)
	driverConfig.SetSamplingRate(100)
	driverConfig.SetOpenSamplingLog(true)
	driverConfig.SetDriverLogSwitch(false)
	driverConfig.SetPlatformMetricSwitch(true)

	zagDriver := zagHandler.GraphToZagDriver[entities.RequestContext, entities.User, entities.Item](graph, driverConfig)
	zagDriver.ToString(graph_constant.ApiStreamChatSub)
	log.Infof(context.Background(), "GraphToZagDriver end. sceneName: %s", graph_constant.ApiStreamChatSub)
	return &DirectChatSubService{
		zagDriver: zagDriver,
	}
}

func (r *DirectChatSubService) runGraph(ctx context.Context, bizRequestContext *entities.RequestContext) ([]*entities.Item, error) {
	timeout := int64(600 * 1000) // 主图10分钟
	scenes := fmt.Sprintf("%s.%s", graph_constant.ApiStreamChatSub, proto.ChatType_ZHIDA_AGENT.String())
	config := strategyEntities.NewRuntimeConfig[entities.RequestContext, entities.User, entities.Item](macro.ResponseNode, scenes, timeout)

	memberID := bizRequestContext.MemberId()
	var requestId string
	if ctx.Value(constant.TraceIdKey) != nil {
		requestId = ctx.Value(constant.TraceIdKey).(string)
	} else {
		requestId = tools.GetNextId()
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

func (r *DirectChatSubService) Handle(ctx context.Context, requestContext *entities.RequestContext) ([]*entities.Item, error) {
	// 执行
	items, err := r.runGraph(ctx, requestContext)
	return items, err
}

type ResearchChatSubService struct {
	zagDriver *zagMap.ZagDriverImpl[data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]]
}

func NewResearchChatSubService() IGraphService {
	graph := api.ResearchChatSubGraph[entities.RequestContext, entities.User, entities.Item]()
	//逻辑图 >>>物理图
	driverConfig := zagDriverEntities.NewDriverConfig() //物理图执行器配置
	driverConfig.SetMaxConcurrency(1000000)
	driverConfig.SetUsePool(false)
	driverConfig.SetSamplingRate(100)
	driverConfig.SetOpenSamplingLog(true)
	driverConfig.SetDriverLogSwitch(false)
	driverConfig.SetPlatformMetricSwitch(true)

	zagDriver := zagHandler.GraphToZagDriver[entities.RequestContext, entities.User, entities.Item](graph, driverConfig)
	zagDriver.ToString(graph_constant.ApiResearchStreamChatSub)
	log.Infof(context.Background(), "GraphToZagDriver end. sceneName: %s", graph_constant.ApiResearchStreamChatSub)
	return &ResearchChatSubService{
		zagDriver: zagDriver,
	}
}

func (r *ResearchChatSubService) runGraph(ctx context.Context, bizRequestContext *entities.RequestContext) ([]*entities.Item, error) {
	timeout := int64(600 * 1000) // 主图10分钟
	scenes := fmt.Sprintf("%s.%s", graph_constant.ApiResearchStreamChatSub, proto.ChatType_ZHIDA_AGENT.String())
	config := strategyEntities.NewRuntimeConfig[entities.RequestContext, entities.User, entities.Item](macro.ResponseNode, scenes, timeout)

	memberID := bizRequestContext.MemberId()
	var requestId string
	if ctx.Value(constant.TraceIdKey) != nil {
		requestId = ctx.Value(constant.TraceIdKey).(string)
	} else {
		requestId = tools.GetNextId()
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

func (r *ResearchChatSubService) Handle(ctx context.Context, requestContext *entities.RequestContext) ([]*entities.Item, error) {
	// 执行
	items, err := r.runGraph(ctx, requestContext)
	return items, err
}
