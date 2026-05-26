package mapping

import (
	"context"
	"strings"

	macro2 "git.in.zhihu.com/zhihu/aisp-core/pkg/basic/macro"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/entities"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/conf"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/logic"
	"git.in.zhihu.com/zhihu/aisp-core/pkg/graph/graph/macro"
	"git.in.zhihu.com/zrec/zrec-framework/pkg/core/data_frame"
	"github.com/samber/lo"
)

// OverwriteConfigLogic 覆盖config逻辑。现在实现了被agent覆盖config，后续可以扩展到通过ab覆盖config
// @logicConfig: 0 | graphBizType 图的bizType
// @logicConfig: 1 | overwriteConfigBy 通过什么来重写config
// @logicInput: 0 | intention string
type OverwriteConfigLogic struct {
	*logic.MappingLogicDecorator[entities.RequestContext, entities.User, entities.Item]
	overwriteFuncMap  map[string]func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], items []*data_frame.ItemData[entities.Item]) map[string]map[string]string
	strategyIdFuncMap map[string]func(ctx context.Context, strategyId string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string
}

func NewOverwriteConfigLogic(name string, config map[string]string) *OverwriteConfigLogic {
	res := &OverwriteConfigLogic{
		MappingLogicDecorator: logic.NewMappingLogicDecorator[entities.RequestContext, entities.User, entities.Item](name, config),
	}

	res.MappingFunc = res.overwriteConfig
	res.overwriteFuncMap = res.genOverwriteFunc()
	res.strategyIdFuncMap = res.genStrategyIdFuncMap()
	return res
}

func (l *OverwriteConfigLogic) genOverwriteFunc() map[string]func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], items []*data_frame.ItemData[entities.Item]) map[string]map[string]string {
	return map[string]func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], items []*data_frame.ItemData[entities.Item]) map[string]map[string]string{
		"agent": func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], items []*data_frame.ItemData[entities.Item]) map[string]map[string]string {
			graphBizType := conf.BuildLogicConfigName(requestCtx.GetBizContext().GetApi(), requestCtx.GetBizContext().GetBizType())
			agent, _ := requestCtx.DataMap().GetString(ctx, macro.ZagKeyIntention)
			graphConfig, _ := conf.GetGraphConfig(graphBizType)
			exps := requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.OverwriteStrategyExp)
			strategyId := l.getAgentStrategyId(ctx, graphConfig, agent, exps, requestCtx)
			confMap := graphConfig.GetOverwriteBizConfigMap(strategyId)
			return confMap
		},
		macro2.AuthorSelf: func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], items []*data_frame.ItemData[entities.Item]) map[string]map[string]string {
			graphBizType := conf.BuildLogicConfigName(requestCtx.GetBizContext().GetApi(), requestCtx.GetBizContext().GetBizType())
			isAuthSelf := false
			// 搜自己时变更
			for _, item := range items {
				if item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ContainSource(conf.KbSourceAuthorSelf) {
					isAuthSelf = true
					graphConfig, _ := conf.GetGraphConfig(graphBizType)
					return graphConfig.GetOverwriteBizConfigMap(macro2.AuthorSelf)
				}
			}
			// 判断是不是创作者自身 或 白名单用户，如果是则直接返回
			// 如果包含搜自己，那么只返回搜自己
			if isAuthSelf && len(requestCtx.GetBizContext().GetRecallContentIds()) > 0 {
				isNotExistSelf := true
				// 命中重答 且 搜自己时变更(需要与原始配置保持一致 唯一变化的时 after 对于self的处理逻辑)
				for _, item := range items {
					// 重答模式下，用户选择的召回内容如果包含白名单和创作者自身，则直接全部使用白名单和创作者自身的召回内容
					if lo.Contains(requestCtx.GetBizContext().GetRecallContentIds(), item.GetBizItem().GetItemRecallContentId()) &&
						item.GetBizItem().GetItemMeta().GetRecallSourceInfo().ContainSource(conf.KbSourceAuthorSelf) {
						isNotExistSelf = false
						break
					}
				}
				if isNotExistSelf {
					graphConfig, _ := conf.GetGraphConfig(graphBizType)
					return graphConfig.GetOverwriteBizConfigMap(macro2.ReAnswerAuthorSelf)
				}
			}
			return nil
		},
		macro2.EmptyRecall: func(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item], items []*data_frame.ItemData[entities.Item]) map[string]map[string]string {
			graphBizType := conf.BuildLogicConfigName(requestCtx.GetBizContext().GetApi(), requestCtx.GetBizContext().GetBizType())
			if len(items) == 0 {
				// 空召回时处理
				graphConfig, _ := conf.GetGraphConfig(graphBizType)
				strategyId := l.getEmptyRecallStrategyId(ctx, requestCtx)
				return graphConfig.GetOverwriteBizConfigMap(strategyId)
			}
			return nil
		},
	}
}

func (l *OverwriteConfigLogic) overwriteConfig(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	user *data_frame.UserData[entities.User], items []*data_frame.ItemData[entities.Item]) ([]*data_frame.ItemData[entities.Item], error) {
	var overwriteConfigMap map[string]map[string]string
	overwriteConfigBys := requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.OverwriteConfigBy)
	for _, overwriteConfigBy := range strings.Split(overwriteConfigBys, ",") {
		if overwriteFunc, exist := l.overwriteFuncMap[overwriteConfigBy]; exist {
			overwriteConfigMap = overwriteFunc(ctx, requestCtx, items)
		}
	}

	l.overwriteLogicConfig(requestCtx, overwriteConfigMap)
	return items, nil
}

func (l *OverwriteConfigLogic) overwriteLogicConfig(requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item],
	overwriteConfigMap map[string]map[string]string) {
	requestCtx.GetBizContext().SetLogicConfigMap(overwriteConfigMap)
}

func (l *OverwriteConfigLogic) getAgentStrategyId(ctx context.Context, graphConfig conf.LogicConfig, agent string, exps string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	strategyId := graphConfig.GetOverwriteStrategyId(agent)
	if f, exist := l.strategyIdFuncMap[requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.OverwriteConfigStrategy)]; exist {
		strategyId = f(ctx, strategyId, requestCtx)
	}
	if exps != "" {
		strategyId = graphConfig.GetOverwriteStrategyId(agent, strings.Split(exps, ",")...)
	}
	return strategyId
}

func (l *OverwriteConfigLogic) getEmptyRecallStrategyId(ctx context.Context, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	strategyId := macro2.EmptyRecall
	if f, exist := l.strategyIdFuncMap[requestCtx.GetBizContext().GetLogicConfig(l.GetName(), conf.OverwriteConfigStrategy)]; exist {
		strategyId = f(ctx, strategyId, requestCtx)
	}
	return strategyId
}

func (l *OverwriteConfigLogic) genStrategyIdFuncMap() map[string]func(ctx context.Context, strategyId string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
	return map[string]func(ctx context.Context, strategyId string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string{
		"kb_deep_thinking": func(ctx context.Context, strategyId string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
			if strategyId == macro2.GetQueryRouteDirect().String() || strategyId == macro2.GetQueryRouteIdentity().String() || strategyId == macro2.GetQueryRouteCode().String() {
				return strategyId + "_" + macro2.DeepThinking
			}
			if strategyId == macro2.EmptyRecall {
				return macro2.DeepThinkingEmptyRecall
			}
			return strategyId
		},
		"zplus": func(ctx context.Context, strategyId string, requestCtx *data_frame.RequestContext[entities.RequestContext, entities.User, entities.Item]) string {
			strategyId = strategyId + "_" + macro2.ZplusBrand
			brandNames := requestCtx.GetBizContext().GetExtraInfo().GetBrandName()
			if brandNames != nil && len(brandNames) > 0 {
				return strategyId + "_" + brandNames[0]
			}
			return strategyId
		},
	}
}
