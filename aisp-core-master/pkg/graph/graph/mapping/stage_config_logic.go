package mapping

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/common_biz/logics/merge"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// StageConfigLogic stage 阶段配置
type StageConfigLogic struct {
	*merge.MergeLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewStageConfigLogic(name string, config map[string]string) *StageConfigLogic {
	res := &StageConfigLogic{
		MergeLogic: merge.NewMergeLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.MergeFunc = res.overwriteConfig
	return res
}

func (l *StageConfigLogic) overwriteConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	items := lo.Flatten(itemLists)
	dynamicStageConfig, isExist := requestCtx.GetBizContext().GetDynamicStageConfig()
	if !isExist {
		return items, nil
	}

	stageTypeStr := requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.StageTypeConfig)
	dynamicBizLogicConfigMap := dynamicStageConfig.GetDynamicBizLogicConfig(ctx, conf.StageType(stageTypeStr), requestCtx, user)
	l.overwriteLogicConfig(requestCtx, dynamicBizLogicConfigMap)
	return items, nil
}

func (l *StageConfigLogic) overwriteLogicConfig(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	overwriteConfigMap map[string]map[string]string) {
	requestCtx.GetBizContext().SetLogicConfigMap(overwriteConfigMap)
}
