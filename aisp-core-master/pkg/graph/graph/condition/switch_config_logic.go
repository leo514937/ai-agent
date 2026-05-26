package condition

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
)

type SwitchConditionLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]

	defaultBranch   string
	switchBranchMap map[string]string
}

func NewSwitchConditionLogic(name string, config map[string]string) *SwitchConditionLogic {
	res := &SwitchConditionLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.MappingFunc = res.empty
	res.SetChooseKeyFunc(res.chooseKey)

	res.defaultBranch = config[conf.ConfigSwitchConditionDefaultBranch]
	err := util.JSONUnmarshal([]byte(config[conf.ConfigSwitchConditionSwitchBranchMap]), &res.switchBranchMap)
	if err != nil {
		panic("SwitchConditionLogic switchBranchMap unmarshal error")
	}

	return res
}

func (q *SwitchConditionLogic) chooseKey(ctx context.Context, reqCtx *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	judgeValue, _ := reqCtx.RequestContext.DataMap().GetString(ctx, q.GetInputName(0))

	branch, ok := q.switchBranchMap[judgeValue]
	if ok {
		return branch
	} else {
		return q.defaultBranch
	}
}

func (q *SwitchConditionLogic) empty(ctx context.Context,
	requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	return items, nil
}
