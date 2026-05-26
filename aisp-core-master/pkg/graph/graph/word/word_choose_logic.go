package word

import (
	"context"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/basic/util"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/logics/framework"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 词条件边选择

// WordChooseLogic 词选择算子
type WordChooseLogic struct {
	*framework.GetListLogic[entities.RequestContext, entities.User, entities.Item]
}

func NewWordChooseLogic(name string, config map[string]string) *WordChooseLogic {
	res := &WordChooseLogic{
		GetListLogic: framework.NeGetListLogic[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.GetListFunc = res.emptyFunc
	// 选择条件边
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (c *WordChooseLogic) emptyFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User]) ([]*data_frame.ItemData[entities.Item], error) {
	return []*data_frame.ItemData[entities.Item]{}, nil
}

func (c *WordChooseLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "WordChooseLogic.chooseKey")
	defer span.Finish()

	logger := log.WithFields(ctx, map[string]interface{}{
		"func": "WordChooseLogic.chooseKey",
	})

	chooseQueriesType := param.RequestContext.GetBizContext().GetSuggestQueriesType().String()
	logger.Infof(ctx, "chooseQueriesType: %s", chooseQueriesType)
	// 打点记录
	util.TimingInMilSec(ctx, macro.CommonStatsPrefix+".word.prefab.%s", 1, chooseQueriesType)

	return chooseQueriesType
}
