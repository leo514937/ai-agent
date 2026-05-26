package intention

import (
	"context"

	proto "git.in.zhihu.com/one-rpc-go/grpc-aisp_core_service/aisp_core_service"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

type AlreadyIntentionJudgeLogic struct {
	*framework.MappingLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewAlreadyIntentionJudgeLogic(name string, config map[string]string) *AlreadyIntentionJudgeLogic {
	res := &AlreadyIntentionJudgeLogic{
		MappingLogic: framework.NewMappingLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MappingFunc = res.realMapping
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (i *AlreadyIntentionJudgeLogic) realMapping(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemList []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	return itemList, nil
}

func (i *AlreadyIntentionJudgeLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	switch param.RequestContext.GetBizContext().GetIntention().GetIntentionType() {
	case proto.IntentionType_SEARCH_INTENTION:
		return proto.IntentionType_SEARCH_INTENTION.String()
	case proto.IntentionType_NO_SEARCH_INTENTION:
		return proto.IntentionType_NO_SEARCH_INTENTION.String()
	default:
		return proto.IntentionType_AMBIGUOUS.String()
	}
}
