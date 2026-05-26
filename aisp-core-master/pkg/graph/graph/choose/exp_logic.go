package choose

import (
	"context"
	"fmt"

	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/port/log"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"git.in.zhihu.com/zrec/zrec-utils/zlab"
	"github.com/samber/lo"
)

// @logicAuthor: zhoupengcheng
// @logicInfo: 实验通用算子

// ExpLogic 实验通用算子
type ExpLogic struct {
	*logic.MergeLogicDecorator[entities.RequestContext, entities.User, entities.Item]
}

func NewExpLogic(name string, config map[string]string) *ExpLogic {
	res := &ExpLogic{
		MergeLogicDecorator: logic.NewMergeLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}
	res.MergeFunc = res.emptyFunc
	// 选择条件边
	res.SetChooseKeyFunc(res.chooseKey)
	return res
}

func (c *ExpLogic) emptyFunc(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], itemLists [][]*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "choose.ExpLogic.realMerge")
	defer span.Finish()
	span.LogFields(log.Message("start."), entities.LogUser(user), entities.LogItemLists(itemLists))

	return lo.Flatten(itemLists), nil
}

func (c *ExpLogic) chooseKey(ctx context.Context, param *data_frame.FrameworkContext[entities.RequestContext, entities.User, entities.Item]) string {
	span, ctx, _ := log.StartChildSpanWithContext(ctx, "ExpLogic.chooseKey")
	defer span.Finish()

	expDomain := param.RequestContext.GetBizContext().GetLogicConfig(c.GetName(), conf.ConfigExpDomain)
	expKey := param.RequestContext.GetBizContext().GetLogicConfig(c.GetName(), conf.ConfigExpKey)
	expValue := param.RequestContext.GetBizContext().GetLogicConfig(c.GetName(), conf.ConfigExpValue)
	expDefaultValue := param.RequestContext.GetBizContext().GetLogicConfig(c.GetName(), conf.ConfigExpDefaultValue)

	zLab := zlab.ZlabValue{Key: expKey, Value: expValue, DefaultValue: expDefaultValue}

	logger := log.WithFields(ctx, map[string]interface{}{
		"func":   "ExpLogic.chooseKey",
		"domain": expDomain,
		"key":    zLab.Key,
	})

	// 如果命中 ab 测试 则直接返回 ab测的 条件边
	abContext := param.RequestContext.GetBizContext().GetABContext(expDomain)
	abValue := abContext.GetZlabABValue(zLab)
	uniqueKey := fmt.Sprintf("%s:%s", zLab.Key, abValue)
	logger.Infof(ctx, "AbTest Value => %s", uniqueKey)

	// 存入 tracing set, 后由tracing提交算子统一上报
	expChan := param.RequestContext.GetBizContext().ProcessTracing().Exp
	if len(expChan) < entities.MaxTracingChanSize {
		expChan <- fmt.Sprintf("%s:%s:%s", expDomain, zLab.Key, abValue)
	}
	return uniqueKey
}
